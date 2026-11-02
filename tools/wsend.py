"""python wsend.py '{"t":"session","on":true,"base":true}' ...  -- send ws messages, print events for a few s."""
import asyncio, json, sys, aiohttp
async def main():
    async with aiohttp.ClientSession() as c:
        async with c.ws_connect('http://127.0.0.1:8091/ws') as ws:
            for a in sys.argv[2:]:
                await ws.send_str(a)
            end = asyncio.get_event_loop().time() + float(sys.argv[1])
            while asyncio.get_event_loop().time() < end:
                try:
                    m = await asyncio.wait_for(ws.receive(), 1.0)
                except asyncio.TimeoutError:
                    continue
                if m.type != aiohttp.WSMsgType.TEXT:
                    continue
                d = json.loads(m.data)
                if d.get('type') in ('event', 'log'):
                    print(d.get('msg') or d.get('text') or d)
asyncio.run(main())
