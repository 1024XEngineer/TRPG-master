"""房间级「AI 主持人行动锁」（issue #107）。

锁防的是什么：一次对 AI 主持人的提交是「读世界状态 → 跑 AI 生成叙事 →
写回状态/广播」的一个循环。两个玩家几乎同时提交时，如果两个循环并发执行，
它们读到的是**同一份旧状态**，各自生成的叙事会互相矛盾（A「我打开门」、
B 同时「我把门锁上」——两次调用都以为门还关着，产出两条打架的剧情分支）。
这跟 AI 聪不聪明无关：它没法对一个还没写回的、正在别处计算中的变化做出
反应。所以同一房间同一时刻只允许一个循环在跑，其他人的提交直接拒绝
（`ACTION_IN_PROGRESS`，不排队不合并——产品形态本来就是"讨论完由一个人
提交"，见 issue #107 关键决策）。

这也如实模拟了真实跑团：守秘人一次只能处理一个人的话，哪怕只是随口一问，
其他人也得等守秘人腾出手。所以锁不区分"行动还是提问"——统一排队。

🔴 超时兜底：锁必须能自己过期。否则一次 AI 调用失败/超时若没走到 release
（代码路径漏了、进程内异常逃逸），房间就永久锁死，之后谁都无法再提交。
规则是：拿锁 → AI 回应完成或超时 → 无条件释放。ws.py 里用 try/finally
保证正常路径的释放，这里的过期时间是最后一道保险。

实现是**进程内存** dict（跟 ws_manager.ConnectionManager 同一档次的取舍）：
本期单进程部署，多进程/多实例时锁不共享——真到那一步需要换成数据库行锁或
Redis，注释在此立此存照。
"""

import time


class RoomActionLockManager:
    # DeepSeek 客户端自身超时 30s（app/core/narrator.py），锁的过期时间给出
    # 一倍余量：正常路径远在 60s 内走到 finally release，走不到时这里兜底。
    LOCK_TIMEOUT_SECONDS = 60.0

    def __init__(self) -> None:
        # room_id -> 锁的到期时刻（time.monotonic() 基准，不受系统时钟回拨影响）
        self._expiry: dict[str, float] = {}

    def try_acquire(self, room_id: str) -> bool:
        """尝试拿锁：没人持有、或持有者已过期（超时兜底）→ 拿到，返回 True；
        否则返回 False，调用方应拒绝这次提交。"""
        now = time.monotonic()
        expiry = self._expiry.get(room_id)
        if expiry is not None and now < expiry:
            return False
        self._expiry[room_id] = now + self.LOCK_TIMEOUT_SECONDS
        return True

    def release(self, room_id: str) -> None:
        """释放锁。释放一个不存在/已过期的锁是无害的空操作——finally 里
        无条件调用，不需要调用方判断状态。"""
        self._expiry.pop(room_id, None)


action_lock_manager = RoomActionLockManager()
