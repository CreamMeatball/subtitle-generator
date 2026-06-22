/**
 * 익명 사용 카운터 (Cloudflare Worker + KV).
 *
 * 앱이 ?event=install / ?event=launch 로 호출하면 해당 카운트를 1 올립니다.
 * 개인정보는 저장하지 않고 단순 합계만 셉니다.
 *
 * 조회: 브라우저에서  https://<worker-url>/?view=1  → {"install":N,"launch":M}
 *
 * 사전 준비: KV 네임스페이스를 만들고 이 워커에 변수명 COUNTER 로 바인딩하세요.
 * (자세한 절차는 ANALYTICS.md 참고)
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Content-Type': 'application/json; charset=utf-8',
    };

    // 카운트 조회(증가 안 함)
    if (url.searchParams.get('view') !== null) {
      const install = parseInt((await env.COUNTER.get('count:install')) || '0', 10);
      const launch = parseInt((await env.COUNTER.get('count:launch')) || '0', 10);
      return new Response(JSON.stringify({ install, launch }), { headers: cors });
    }

    // 이벤트 카운트 증가 (영문 소문자만 허용)
    let event = (url.searchParams.get('event') || 'launch').toLowerCase().replace(/[^a-z]/g, '');
    if (event !== 'install' && event !== 'launch') event = 'launch';

    const key = `count:${event}`;
    const cur = parseInt((await env.COUNTER.get(key)) || '0', 10) || 0;
    await env.COUNTER.put(key, String(cur + 1));

    return new Response(JSON.stringify({ event, count: cur + 1 }), { headers: cors });
  },
};
