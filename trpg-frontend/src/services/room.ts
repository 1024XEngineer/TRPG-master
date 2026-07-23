import type { CreateRoomResult, ModuleSummary, MyRoomSummary, RoomPreview } from 'trpg-sdk';
import { useRoomStore } from '@/stores/room-store';
import { getAuthToken, sdk } from './api-client';

export type { CreateRoomResult, ModuleSummary, MyRoomSummary, RoomPreview };

// 房主/已加入玩家专属的操作（选模组/开始游戏/结束游戏/我的房间列表）需要
// 后端的房间重连凭证（X-Reconnect-Token，issue #39），加入/创建房间时签发、
// 存进 room-store——直接从 store 读，页面组件不需要在每次调用时手动传。
function requireReconnectToken(): string {
  const token = useRoomStore.getState().reconnectToken;
  if (!token) throw new Error('缺少房间重连凭证，请重新加入房间');
  return token;
}

// 创建/加入房间和「我的游戏」用的是**账号**凭证，不是上面那个房间凭证
// （issue #106）。两者分工：账号解决跨设备/跨时间找回，reconnectToken 解决
// 同一局进行中的快速重连。
function requireAuthToken(): string {
  const token = getAuthToken();
  if (!token) throw new Error('请先登录');
  return token;
}

// 创建房间（房主创建即加入，见 §5.2.5）
export async function createGameRoom(
  nickname?: string,
  roomName?: string,
  maxPlayers?: number
): Promise<CreateRoomResult> {
  return sdk.rooms.create(
    { nickname, roomName: roomName ?? '', maxPlayers: maxPlayers ?? 4 },
    requireAuthToken()
  );
}

// 拉取可用模组列表（本次没有做模组导入，只有一款内置模拟模组）
export async function listModules(): Promise<ModuleSummary[]> {
  return sdk.rooms.listModules();
}

// 房主确定模组
export async function selectModule(roomId: string, moduleId: string): Promise<void> {
  await sdk.rooms.selectModule(
    roomId,
    { moduleId, attributeGenMethod: 'point_buy' },
    requireReconnectToken()
  );
}

// 用房间码加入房间。issue #106 起后端按**账号**幂等：已经是这个房间的成员时
// 原样返回既有身份，所以这个函数同时承担「加入」和「掉线/换设备后重连」两个
// 用途——之前那句「已是本房间玩家则幂等返回已有身份」的注释是假的，后端当时
// 根本不检查，重复调用会给同一个人建重复玩家行。
export async function joinRoomByCode(
  roomCode: string,
  nickname?: string
): Promise<CreateRoomResult> {
  return sdk.rooms.join(roomCode, { nickname }, requireAuthToken());
}

// 获取房间信息（房间码预览）
export async function getRoomInfo(roomCode: string): Promise<RoomPreview> {
  return sdk.rooms.getInfo(roomCode);
}

// 房主点击「开始游戏」，从大厅推进到背景介绍——访客端轮询这个标记自动跟进
export async function startStory(roomId: string): Promise<void> {
  await sdk.rooms.startStory(roomId, requireReconnectToken());
}

// 我的房间列表——用于「浏览已有游戏」入口。issue #106 起按**账号**返回该用户
// 参与过的全部房间（换台设备登录同一账号也能看到），不再是「这个浏览器的最后
// 一个房间」。没登录时返回空列表而不是报错：这个入口在未登录状态下也会被渲染。
export async function listMyRooms(): Promise<MyRoomSummary[]> {
  const token = getAuthToken();
  if (!token) return [];
  return sdk.rooms.listMyRooms(token);
}

// 房主结束游戏，房间转入「已完成」状态，之后只能查看复盘
export async function endGame(roomId: string): Promise<void> {
  await sdk.rooms.endGame(roomId, requireReconnectToken());
}
