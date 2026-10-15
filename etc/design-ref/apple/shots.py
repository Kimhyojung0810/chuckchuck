import asyncio
from playwright.async_api import async_playwright
PAGES = {'iphone': 'https://www.apple.com/kr/iphone/', 'watch': 'https://www.apple.com/kr/watch/', 'newsroom': 'https://www.apple.com/kr/newsroom/', 'home': 'https://www.apple.com/kr/'}
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for k, u in PAGES.items():
            pg = await b.new_page(viewport={'width': 1440, 'height': 900})
            try:
                await pg.goto(u, wait_until='networkidle', timeout=45000)
            except Exception as e:
                print(k, 'timeout', str(e)[:60])
            await pg.wait_for_timeout(1500)
            for i in range(3):
                await pg.evaluate(f'window.scrollTo(0, {i * 900})'); await pg.wait_for_timeout(900)
                await pg.screenshot(path=f'shots/{k}_{i + 1}.jpg', type='jpeg', quality=70)
            await pg.close(); print(k, 'ok')
        await b.close()
asyncio.run(main())
