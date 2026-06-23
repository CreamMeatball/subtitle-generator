/**
 * 익명 사용 카운터 (Cloudflare Worker + KV).
 *
 * 앱이 ?event=install / ?event=launch 로 호출하면 카운트를 1 올립니다.
 * 개인정보는 저장하지 않고 단순 합계만 셉니다.
 *
 * 조회(브라우저에서):
 *   .../?view=1    → {"install":N,"launch":M}                 (전체 누적, 기존 호환)
 *   .../?stats=1   → {"total":{...}, "monthly":{"2026-06":{...}, ...}}  (월별 통계)
 *
 * 사전 준비: KV 네임스페이스를 만들고 이 워커에 변수명 COUNTER 로 바인딩하세요.
 * (자세한 절차는 ANALYTICS.md 참고)
 *
 * ※ 월별 분해는 이 버전을 배포한 시점부터 쌓입니다(과거치는 전체 누적에만 남아 있음).
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Content-Type': 'application/json; charset=utf-8',
    };
    const getN = async (k) => parseInt((await env.COUNTER.get(k)) || '0', 10) || 0;

    // 월별 통계 조회 (증가 안 함)
    if (url.searchParams.get('stats') !== null) {
      const total = { install: await getN('count:install'), launch: await getN('count:launch') };
      let months = [];
      try { months = JSON.parse((await env.COUNTER.get('months')) || '[]'); } catch (e) {}
      months.sort();
      const monthly = {};
      for (const m of months) {
        monthly[m] = {
          install: await getN(`count:install:${m}`),
          launch: await getN(`count:launch:${m}`),
        };
      }
      return new Response(JSON.stringify({ total, monthly }, null, 2), { headers: cors });
    }

    // 전체 누적 조회 (기존 호환, 증가 안 함)
    if (url.searchParams.get('view') !== null) {
      const install = await getN('count:install');
      const launch = await getN('count:launch');
      return new Response(JSON.stringify({ install, launch }), { headers: cors });
    }

    // 이벤트 카운트 증가 (영문 소문자만 허용)
    let event = (url.searchParams.get('event') || 'launch').toLowerCase().replace(/[^a-z]/g, '');
    if (event !== 'install' && event !== 'launch') event = 'launch';

    // YYYY-MM (UTC 기준)
    const now = new Date();
    const ym = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;

    // 전체 누적 + 월별 누적
    await env.COUNTER.put(`count:${event}`, String((await getN(`count:${event}`)) + 1));
    await env.COUNTER.put(`count:${event}:${ym}`, String((await getN(`count:${event}:${ym}`)) + 1));

    // 월 인덱스 갱신(처음 보는 달만)
    let months = [];
    try { months = JSON.parse((await env.COUNTER.get('months')) || '[]'); } catch (e) {}
    if (!months.includes(ym)) {
      months.push(ym);
      await env.COUNTER.put('months', JSON.stringify(months));
    }

    return new Response(JSON.stringify({ event, ym }), { headers: cors });
  },
};
