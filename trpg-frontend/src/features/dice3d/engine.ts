/**
 * 3D 骰子舞台：构建骰子、跑物理、自然定格取值（issue #217）。
 *
 * 与 React 无关，只认一个容器元素和一个回调，方便单独调试与替换。
 * 这个模块会 import three，所以调用方应当**动态 import 它**，不要静态引入
 * ——否则 three 会进首屏包。
 *
 * ## 结果怎么来的
 * 不预先挑结果面，而是让骰子自然停下、读此刻朝上的那一面。这样数字与肉眼看到
 * 的面永远一致；原型第一版是"先定值再把目标面掰上来"，表现为动画放完后骰子突然
 * 又转一下，很突兀。
 *
 * 均匀性由 `shuffle()` 保证（见该文件注释），与物理是否有偏无关。
 */
import {
  AmbientLight,
  BufferGeometry,
  Color,
  DirectionalLight,
  Euler,
  Float32BufferAttribute,
  Group,
  Mesh,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  PCFSoftShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PointLight,
  Quaternion,
  SRGBColorSpace,
  Scene,
  ShadowMaterial,
  Vector3,
  WebGLRenderer,
} from 'three'

import { resolveSphereCollision, separatePlanarTargets } from './collision'
import { faceNormal, polyhedronFaces } from './geometry'
import { shuffle } from './shuffle'
import { PALETTES, makeFaceTexture, type Palette } from './textures'
import type { DiceKind, PolyhedronKind } from './types'

const GRAVITY = -14
const ARENA = { halfX: 2.9, halfZ: 1.35, floorY: 0 }
/** 安全上限，防止物理异常时永远不结束。 */
const MAX_TUMBLE_SECONDS = 4.5
const SETTLE_SECONDS = 0.55

interface FaceInfo {
  value: number
  normal: Vector3
}

interface Die {
  group: Group
  /** 静止时质心离地高度：以面着地，取内切半径。 */
  restY: number
  /** 仅用于轻量骰子间碰撞的保守包围半径。 */
  collisionRadius: number
  faces: FaceInfo[]
}

interface DiceActor {
  die: Die
  value: number | null
  vel: Vector3
  angAxis: Vector3
  angSpeed: number
  qStart?: Quaternion
  qTarget?: Quaternion
  pStart?: Vector3
  pTarget?: Vector3
}

function rand(min: number, max: number): number {
  return Math.random() * (max - min) + min
}

/** 构建一颗骰子：逐面独立网格 + 贴图，外加一个内芯防止面片缝隙透光。 */
function buildDie(
  kind: PolyhedronKind,
  palette: Palette,
  values: number[],
  labels: string[],
): Die {
  const polys = polyhedronFaces(kind)
  const group = new Group()
  const faces: FaceInfo[] = []
  const coreTris: number[] = []
  let minInradius = Infinity
  let maxVertexRadius = 0
  const usePips = kind === 'd6'

  polys.forEach((verts, faceIndex) => {
    for (const vertex of verts) maxVertexRadius = Math.max(maxVertexRadius, vertex.length())
    // 保证顶点绕序让法线朝外。
    const normal = faceNormal(verts)
    const centroid = new Vector3()
    for (const v of verts) centroid.add(v)
    centroid.divideScalar(verts.length)
    if (normal.dot(centroid) < 0) {
      verts.reverse()
      normal.negate()
    }
    minInradius = Math.min(minInradius, Math.abs(centroid.dot(normal)))

    // UV：把面投影到它自己的平面基上，再归一化到 0–1 并留边距。
    const u = new Vector3().subVectors(verts[1], verts[0]).normalize()
    const w = new Vector3().crossVectors(normal, u).normalize()
    const flat = verts.map((v) => {
      const d = new Vector3().subVectors(v, verts[0])
      return [d.dot(u), d.dot(w)] as [number, number]
    })
    const xs = flat.map((p) => p[0])
    const ys = flat.map((p) => p[1])
    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)
    const pad = 0.07
    const uvPoly = flat.map(
      ([px, py]) =>
        [
          pad + ((px - minX) / (maxX - minX || 1)) * (1 - 2 * pad),
          pad + ((py - minY) / (maxY - minY || 1)) * (1 - 2 * pad),
        ] as [number, number],
    )

    // 扇形三角化。
    const positions: number[] = []
    const uvs: number[] = []
    for (let t = 1; t < verts.length - 1; t += 1) {
      for (const idx of [0, t, t + 1]) {
        positions.push(verts[idx].x, verts[idx].y, verts[idx].z)
        uvs.push(uvPoly[idx][0], uvPoly[idx][1])
        coreTris.push(verts[idx].x, verts[idx].y, verts[idx].z)
      }
    }
    const geom = new BufferGeometry()
    geom.setAttribute('position', new Float32BufferAttribute(positions, 3))
    geom.setAttribute('uv', new Float32BufferAttribute(uvs, 2))
    geom.computeVertexNormals()

    const tex = makeFaceTexture(
      palette,
      labels[faceIndex],
      uvPoly,
      usePips ? values[faceIndex] : undefined,
    )
    const mesh = new Mesh(
      geom,
      new MeshPhysicalMaterial({
        map: tex,
        roughness: 0.32,
        metalness: 0.05,
        clearcoat: 0.7,
        clearcoatRoughness: 0.25,
      }),
    )
    mesh.castShadow = true
    group.add(mesh)

    faces.push({ value: values[faceIndex], normal: normal.clone() })
  })

  const coreGeom = new BufferGeometry()
  coreGeom.setAttribute('position', new Float32BufferAttribute(coreTris, 3))
  coreGeom.computeVertexNormals()
  const core = new Mesh(
    coreGeom,
    new MeshStandardMaterial({
      color: new Color(palette.base).multiplyScalar(0.55),
      roughness: 0.6,
    }),
  )
  core.scale.setScalar(0.985)
  group.add(core)

  return {
    group,
    restY: minInradius,
    collisionRadius: maxVertexRadius * 0.88,
    faces,
  }
}

function disposeGroup(group: Group): void {
  group.traverse((obj) => {
    const mesh = obj as Mesh
    if (mesh.geometry) mesh.geometry.dispose()
    const material = mesh.material
    if (!material) return
    for (const m of Array.isArray(material) ? material : [material]) {
      const mapped = m as MeshPhysicalMaterial
      if (mapped.map) mapped.map.dispose()
      m.dispose()
    }
  })
}

/** 每颗骰子的面值表与摆放位置。D100 = 十位骰 + 个位骰。 */
function diceDefinitions(kind: DiceKind): {
  poly: PolyhedronKind
  palette: Palette
  values: number[]
  labels: string[]
  restX: number
}[] {
  if (kind === 'd100') {
    const tens = shuffle([0, 10, 20, 30, 40, 50, 60, 70, 80, 90])
    const units = shuffle([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    return [
      {
        poly: 'd10',
        palette: PALETTES.d100tens,
        values: tens,
        labels: tens.map((v) => (v === 0 ? '00' : String(v))),
        restX: -1.05,
      },
      {
        poly: 'd10',
        palette: PALETTES.d100units,
        values: units,
        labels: units.map(String),
        restX: 1.05,
      },
    ]
  }
  const sides = kind === 'd20' ? 20 : 6
  const values = shuffle(Array.from({ length: sides }, (_, i) => i + 1))
  return [
    {
      poly: kind,
      palette: kind === 'd20' ? PALETTES.d20 : PALETTES.d6,
      values,
      labels: values.map(String),
      restX: 0,
    },
  ]
}

export interface DiceStage {
  /** 掷一次。正在掷的时候重复调用会被忽略。 */
  roll: () => boolean
  /** 释放 WebGL 资源并停掉动画循环。 */
  dispose: () => void
}

export interface DiceStageOptions {
  container: HTMLElement
  kind: DiceKind
  /** 骰子完全停稳、结果可读时调用一次。 */
  onSettled: (value: number) => void
}

export function createDiceStage({ container, kind, onSettled }: DiceStageOptions): DiceStage {
  const renderer = new WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = PCFSoftShadowMap
  // 原型用的是 r128 的 outputEncoding = sRGBEncoding。
  renderer.outputColorSpace = SRGBColorSpace
  container.appendChild(renderer.domElement)

  const scene = new Scene()
  const camera = new PerspectiveCamera(38, 1, 0.1, 60)
  camera.position.set(0, 5.4, 7.0)
  camera.lookAt(0, 0.1, 0)

  scene.add(new AmbientLight(0xd8e2dc, 0.55))
  const key = new DirectionalLight(0xffffff, 0.95)
  key.position.set(3.5, 7, 4)
  key.castShadow = true
  key.shadow.mapSize.set(1024, 1024)
  key.shadow.camera.left = -5
  key.shadow.camera.right = 5
  key.shadow.camera.top = 5
  key.shadow.camera.bottom = -5
  key.shadow.radius = 4
  scene.add(key)
  const rim = new PointLight(0x4fd1a5, 0.5, 20)
  rim.position.set(-4, 2.5, -3)
  scene.add(rim)
  const warm = new PointLight(0xc9a227, 0.22, 18)
  warm.position.set(4, 1.5, 3)
  scene.add(warm)

  // 地面只承接阴影，本身透明。
  const groundGeom = new PlaneGeometry(24, 24)
  const groundMat = new ShadowMaterial({ opacity: 0.38 })
  const ground = new Mesh(groundGeom, groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.position.y = ARENA.floorY
  ground.receiveShadow = true
  scene.add(ground)

  let actors: DiceActor[] = []
  let phase: 'idle' | 'tumble' | 'align' = 'idle'
  let elapsed = 0
  let alignProgress = 0
  let minTumble = 1.35
  let frame = 0
  let lastFrame = performance.now()
  let disposed = false

  // 让 three 同时写 canvas 的 CSS 尺寸（setSize 的第三参默认 true）。
  // 原型里用的是 setSize(w, h, false)，靠它自己页面的 CSS 把 canvas 拉成 100%；
  // 这里没有那段 CSS，不写 style 的话 canvas 会按绘制缓冲尺寸当 CSS 像素显示
  // ——在 dpr=2 的屏上就是 2 倍大小，父容器 overflow-hidden 只露出左上四分之一。
  renderer.domElement.style.display = 'block'

  const resize = () => {
    const w = container.clientWidth
    const h = container.clientHeight
    if (w === 0 || h === 0) return
    renderer.setSize(w, h)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
  }
  resize()

  const observer =
    typeof ResizeObserver === 'function' ? new ResizeObserver(() => resize()) : null
  observer?.observe(container)

  const clearActors = () => {
    for (const actor of actors) {
      scene.remove(actor.die.group)
      disposeGroup(actor.die.group)
    }
    actors = []
  }

  /** 找出此刻法线最朝上的面——就是玩家看到的那一面。 */
  const findTopFace = (die: Die): FaceInfo => {
    let best = -Infinity
    let bestFace = die.faces[0]
    for (const face of die.faces) {
      const worldY = face.normal.clone().applyQuaternion(die.group.quaternion).y
      if (worldY > best) {
        best = worldY
        bestFace = face
      }
    }
    return bestFace
  }

  const readValue = (): number => {
    if (kind === 'd100') {
      const tens = actors[0]?.value ?? 0
      const units = actors[1]?.value ?? 0
      const total = tens + units
      return total === 0 ? 100 : total
    }
    return actors[0]?.value ?? 1
  }

  const enterAlign = () => {
    phase = 'align'
    alignProgress = 0
    const targets = actors.map((actor) => ({
      x: actor.die.group.position.x,
      z: actor.die.group.position.z,
    }))
    if (actors.length === 2) {
      const separated = separatePlanarTargets(
        targets[0],
        targets[1],
        actors[0].die.collisionRadius + actors[1].die.collisionRadius,
        { halfX: ARENA.halfX - 0.25, halfZ: ARENA.halfZ - 0.25 },
      )
      targets[0] = separated[0]
      targets[1] = separated[1]
    }

    for (const [index, actor] of actors.entries()) {
      actor.qStart = actor.die.group.quaternion.clone()
      actor.pStart = actor.die.group.position.clone()
      const top = findTopFace(actor.die)
      actor.value = top.value
      // 只做最短弧修正：这一面本来就接近朝上，不会出现大幅突转。
      actor.qTarget = new Quaternion().setFromUnitVectors(
        top.normal.clone(),
        new Vector3(0, 1, 0),
      )
      const target = actor.die.group.position.clone()
      target.x = targets[index].x
      target.y = actor.die.restY
      target.z = targets[index].z
      actor.pTarget = target
    }
  }

  const step = (dt: number) => {
    if (phase === 'tumble') {
      elapsed += dt
      // 前 0.5 秒放开翻滚，之后逐渐加大阻尼让它自己停下来。
      const damp = elapsed > 0.5 ? Math.min((elapsed - 0.5) / 0.8, 1) : 0
      let allResting = true

      for (const actor of actors) {
        const g = actor.die.group
        actor.vel.y += GRAVITY * dt
        g.position.addScaledVector(actor.vel, dt)

        if (g.position.y < actor.die.restY) {
          g.position.y = actor.die.restY
          actor.vel.y = Math.abs(actor.vel.y) * 0.42
          actor.vel.x *= 0.7
          actor.vel.z *= 0.7
          actor.angSpeed *= 0.7
          actor.angAxis.set(rand(-1, 1), rand(-1, 1), rand(-1, 1)).normalize()
          if (actor.vel.y < 0.8) actor.vel.y = 0
        }
        if (g.position.x > ARENA.halfX) {
          g.position.x = ARENA.halfX
          actor.vel.x = -Math.abs(actor.vel.x) * 0.6
        }
        if (g.position.x < -ARENA.halfX) {
          g.position.x = -ARENA.halfX
          actor.vel.x = Math.abs(actor.vel.x) * 0.6
        }
        if (g.position.z > ARENA.halfZ) {
          g.position.z = ARENA.halfZ
          actor.vel.z = -Math.abs(actor.vel.z) * 0.6
        }
        if (g.position.z < -ARENA.halfZ) {
          g.position.z = -ARENA.halfZ
          actor.vel.z = Math.abs(actor.vel.z) * 0.6
        }

        if (damp > 0) {
          actor.angSpeed *= Math.pow(0.06, dt * damp)
          const pk = Math.pow(0.12, dt * damp)
          actor.vel.x *= pk
          actor.vel.z *= pk
        }

        g.quaternion.premultiply(
          new Quaternion().setFromAxisAngle(actor.angAxis, actor.angSpeed * dt),
        )

        // 只看速度会在弹跳顶点误判为静止，必须同时要求真的贴着地面。
        const grounded = Math.abs(g.position.y - actor.die.restY) < 0.03
        if (
          actor.angSpeed > 0.15 ||
          Math.abs(actor.vel.y) > 0.05 ||
          Math.abs(actor.vel.x) > 0.05 ||
          Math.abs(actor.vel.z) > 0.05 ||
          !grounded
        ) {
          allResting = false
        }
      }

      if (actors.length === 2) {
        const collided = resolveSphereCollision(
          {
            position: actors[0].die.group.position,
            velocity: actors[0].vel,
            radius: actors[0].die.collisionRadius,
          },
          {
            position: actors[1].die.group.position,
            velocity: actors[1].vel,
            radius: actors[1].die.collisionRadius,
          },
        )
        if (collided) allResting = false
        for (const actor of actors) {
          const position = actor.die.group.position
          position.x = Math.min(Math.max(position.x, -ARENA.halfX), ARENA.halfX)
          position.y = Math.max(position.y, actor.die.restY)
          position.z = Math.min(Math.max(position.z, -ARENA.halfZ), ARENA.halfZ)
        }
      }

      if ((allResting && elapsed >= minTumble) || elapsed >= MAX_TUMBLE_SECONDS) {
        enterAlign()
      }
    } else if (phase === 'align') {
      alignProgress += dt / SETTLE_SECONDS
      const k = Math.min(alignProgress, 1)
      const ease = 1 - Math.pow(1 - k, 3)
      for (const actor of actors) {
        if (!actor.qStart || !actor.qTarget || !actor.pStart || !actor.pTarget) continue
        actor.die.group.quaternion.slerpQuaternions(actor.qStart, actor.qTarget, ease)
        actor.die.group.position.lerpVectors(actor.pStart, actor.pTarget, ease)
      }
      if (k >= 1) {
        phase = 'idle'
        onSettled(readValue())
      }
    }
  }

  const loop = (now: number) => {
    if (disposed) return
    frame = requestAnimationFrame(loop)
    const dt = Math.min((now - lastFrame) / 1000, 0.05)
    lastFrame = now
    step(dt)
    renderer.render(scene, camera)
  }
  frame = requestAnimationFrame(loop)

  return {
    roll() {
      if (disposed || phase !== 'idle') return false
      clearActors()
      diceDefinitions(kind).forEach((def, index) => {
        const die = buildDie(def.poly, def.palette, def.values, def.labels)
        die.group.position.set(def.restX + rand(-0.6, 0.6), 3.4 + index * 0.7, rand(-0.4, 0.4))
        die.group.quaternion.setFromEuler(
          new Euler(rand(0, 6.28), rand(0, 6.28), rand(0, 6.28)),
        )
        scene.add(die.group)
        actors.push({
          die,
          value: null,
          vel: new Vector3(rand(-2.4, 2.4), rand(-1, 0.5), rand(-1.4, 1.4)),
          angAxis: new Vector3(rand(-1, 1), rand(-1, 1), rand(-1, 1)).normalize(),
          angSpeed: rand(11, 19),
        })
      })
      elapsed = 0
      minTumble = rand(1.2, 1.5)
      phase = 'tumble'
      return true
    },
    dispose() {
      if (disposed) return
      disposed = true
      cancelAnimationFrame(frame)
      observer?.disconnect()
      clearActors()
      groundGeom.dispose()
      groundMat.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}
