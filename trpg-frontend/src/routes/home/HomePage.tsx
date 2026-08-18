import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth-store'

interface SceneActionProps {
  label: string
  image: string
  width: number
  height: number
  onClick: () => void
}

function SceneAction({ label, image, width, height, onClick }: SceneActionProps) {
  return (
    <button
      type="button"
      aria-label={label}
      className="home-scene__action"
      onClick={onClick}
    >
      <img
        src={image}
        alt=""
        aria-hidden="true"
        width={width}
        height={height}
        decoding="async"
      />
      <span className="sr-only">{label}</span>
    </button>
  )
}

export default function HomePage() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const nickname = useAuthStore((s) => s.nickname)

  useEffect(() => {
    if (!isLoggedIn) navigate('/auth/login', { replace: true })
  }, [isLoggedIn, navigate])

  if (!isLoggedIn) return null

  return (
    <section className="home-scene" aria-labelledby="home-scene-title">
      <div className="home-scene__artboard">
        <img
          className="home-scene__background"
          src="/assets/home/background.webp"
          alt=""
          aria-hidden="true"
          width={853}
          height={1844}
        />

        <h1 id="home-scene-title" className="sr-only">
          AI跑团主持人
        </h1>
        <p className="sr-only">AI 智能主持 · 多游戏聚会平台</p>

        <button
          type="button"
          onClick={() => navigate('/home/profile')}
          aria-label={`打开个人信息：${nickname || '未设置昵称'}`}
          className="home-scene__identity"
        >
          <img
            src="/assets/home/nameplate.webp"
            alt=""
            aria-hidden="true"
            width={484}
            height={198}
            decoding="async"
          />
          <span className="home-scene__nickname">{nickname || '未设置昵称'}</span>
        </button>

        <div className="home-scene__actions" role="group" aria-label="房间操作">
          <SceneAction
            label="加入房间"
            image="/assets/home/join-paper.webp"
            width={858}
            height={532}
            onClick={() => navigate('/home/join')}
          />
          <SceneAction
            label="创建房间"
            image="/assets/home/create-paper.webp"
            width={912}
            height={604}
            onClick={() => navigate('/home/create')}
          />
          <SceneAction
            label="我的游戏"
            image="/assets/home/my-games-paper.webp"
            width={914}
            height={565}
            onClick={() => navigate('/home/my-rooms')}
          />
          {/* 纸片上的文字是画进图里的，`label` 只喂 aria-label / 读屏。
              `my-characters-paper.webp` 目前是 my-games-paper 的副本占位，美术
              替换这一个文件即可，不需要动代码。
              还需要美术一并处理的：木框和红绳是按三格排的，第四张现在会掉到
              框外、也没有绳子串上去。 */}
          <SceneAction
            label="我的角色卡"
            image="/assets/home/my-characters-paper.webp"
            width={914}
            height={565}
            onClick={() => navigate('/home/characters')}
          />
          <img
            className="home-scene__pins"
            src="/assets/home/pins-and-string.webp"
            alt=""
            aria-hidden="true"
            width={1024}
            height={1536}
            decoding="async"
          />
        </div>

        <img
          className="home-scene__cat"
          src="/assets/home/detective-cat.webp"
          alt="猫侦探"
          width={615}
          height={829}
          decoding="async"
        />
        <img
          className="home-scene__books"
          src="/assets/home/books.webp"
          alt=""
          aria-hidden="true"
          width={373}
          height={338}
          decoding="async"
        />
        <img
          className="home-scene__newspaper"
          src="/assets/home/newspaper-pen.webp"
          alt=""
          aria-hidden="true"
          width={475}
          height={280}
          decoding="async"
        />
      </div>
    </section>
  )
}
