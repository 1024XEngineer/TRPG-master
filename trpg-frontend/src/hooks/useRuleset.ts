import { useEffect, useState } from 'react';
import type { Ruleset } from 'trpg-sdk';
import { friendlyErrorMessage } from '@/services/api-client';
import { getRuleset } from '@/services/character/ruleset-api';

// 建卡规则目录（职业/技能/属性）——多个页面（建卡向导/人物卡准备页/游戏内
// 角色卡面板）都要用职业名/技能名渲染，统一走这个 hook 拿。`getRuleset()`
// 内部已经做了跨调用缓存，这里多个页面各自调用也只会真正发一次请求。
export function useRuleset() {
  const [ruleset, setRuleset] = useState<Ruleset | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    getRuleset()
      .then((rs) => {
        if (!cancelled) {
          setRuleset(rs);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(friendlyErrorMessage(err, '规则数据加载失败'));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { ruleset, loading, error };
}
