from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parent
output = root.parents[1] / 'web' / 'public' / 'mascot'
output.mkdir(parents=True, exist_ok=True)
for name in ('idle', 'thinking', 'greeting'):
    frames = [Image.open(root / 'frames' / f'{name}-{i:02}.png').convert('RGBA') for i in range(12)]
    frames[0].save(output / f'{name}.webp', format='WEBP', save_all=True,
                   append_images=frames[1:], duration=83, loop=0, quality=88, method=5)
Image.open(root / 'preview.png').save(output / 'still.webp', format='WEBP', quality=92, method=5)
