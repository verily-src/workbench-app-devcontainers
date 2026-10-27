import bpy
from pathlib import Path

out = Path(__file__).resolve().parent / 'frames'
out.mkdir(exist_ok=True)
scene = bpy.context.scene
scene.render.resolution_x = 160
scene.render.resolution_y = 160
scene.cycles.samples = 12
for name, start in [('idle',1), ('thinking',26), ('greeting',51), ('dance',76)]:
    for index in range(24):
        scene.frame_set(start + index)
        scene.render.filepath = str(out / f'{name}-{index:02}.png')
        bpy.ops.render.render(write_still=True)
