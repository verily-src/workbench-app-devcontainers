import bpy
import math
from mathutils import Vector
from pathlib import Path

OUT = Path(__file__).resolve().parent
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

def material(name, color, metallic=0.0, roughness=0.4, emission=0):
    m = bpy.data.materials.new(name); m.diffuse_color = (*color, 1); m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Metallic'].default_value = metallic; p.inputs['Roughness'].default_value = roughness
    if emission:
        p.inputs['Emission Color'].default_value = (*color, 1); p.inputs['Emission Strength'].default_value = emission
    return m

shell = material('soft pearl', (0.94, 0.94, 0.88), .02, .5)
teal = material('deep teal', (0.018, 0.18, 0.16), .12, .24)
light = material('mint light', (0.30, 0.96, 0.76), .05, .24, .3)
accent = material('sea glass', (0.08, 0.61, 0.49), .2, .24)
blush = material('warm coral', (0.98, 0.40, 0.30), .0, .4)

bpy.ops.object.empty_add(location=(0,0,0)); bot=bpy.context.object; bot.name='Mascot control'
def sphere(name, loc, scale, mat, parent=bot):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=loc)
    obj=bpy.context.object; obj.name=name; obj.scale=scale; obj.data.materials.append(mat)
    bpy.ops.object.shade_smooth(); obj.parent=parent
    return obj

sphere('Body', (0,0,1.05), (.67,.48,.69), shell)
sphere('Face housing', (0,-.39,1.22), (.50,.14,.40), teal)
sphere('Left eye',(-.18,-.525,1.30),(.085,.035,.10), light)
sphere('Right eye',(.18,-.525,1.30),(.085,.035,.10), light)
sphere('Left eye glint',(-.20,-.558,1.33),(.021,.012,.025), shell)
sphere('Right eye glint',(.16,-.558,1.33),(.021,.012,.025), shell)
sphere('Left cheek',(-.31,-.508,1.14),(.060,.016,.033), blush)
sphere('Right cheek',(.31,-.508,1.14),(.060,.016,.033), blush)
curve = bpy.data.curves.new('smile', 'CURVE'); curve.dimensions = '3D'; curve.bevel_depth = .013; curve.bevel_resolution = 3
line = curve.splines.new('BEZIER'); line.bezier_points.add(2)
for point, co in zip(line.bezier_points, [(-.09,-.529,1.12),(0,-.543,1.08),(.09,-.529,1.12)]):
    point.co = co; point.handle_left_type = point.handle_right_type = 'AUTO'
smile = bpy.data.objects.new('Smile', curve); bpy.context.collection.objects.link(smile); smile.parent = bot; smile.data.materials.append(light)
sphere('Belly badge',(0,-.415,.73),(.135,.035,.135),accent)
sphere('Badge light',(0,-.448,.73),(.06,.018,.06),light)
for x, angle in [(-.025, -.55), (.025, .55)]:
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x,-.468,.73))
    mark = bpy.context.object; mark.name = 'Verily-inspired V'
    mark.scale = (.018,.012,.08); mark.rotation_euler.y = angle
    mark.data.materials.append(shell); mark.parent = bot
sphere('Left foot',(-.31,-.06,.43),(.26,.34,.16),shell)
sphere('Right foot',(.31,-.06,.43),(.26,.34,.16),shell)
sphere('Left ear',(-.59,0,1.37),(.12,.20,.19),accent)
sphere('Right ear',(.59,0,1.37),(.12,.20,.19),accent)
sphere('Left hand',(-.62,-.02,.91),(.18,.20,.25),shell)
bpy.ops.object.empty_add(location=(.55,0,1.05)); arm=bpy.context.object; arm.name='Wave arm'; arm.parent=bot
hand=sphere('Right hand',(.67,-.02,.91),(.18,.20,.25),shell,parent=arm)
# Parenting retains local coordinates unless reset; arm uses the hand offset.
hand.location=(.12,-.02,-.14)
sphere('Antenna base',(0,0,1.70),(.095,.095,.11),accent)
sphere('Antenna stem',(0,0,1.83),(.035,.035,.13),teal)
sphere('Antenna light',(0,0,1.96),(.09,.09,.09),light)

# Three short, separately labeled animation ranges, each with matching end frames.
for start, end, name in [(1,25,'Idle'),(26,50,'Thinking'),(51,75,'Greeting')]:
    for frame in range(start,end+1):
        t=2*math.pi*(frame-start)/(end-start)
        bot.location.z=.018*math.sin(t); bot.rotation_euler=(0, .025*math.sin(t), .018*math.sin(t))
        arm.rotation_euler=(0, 0, 0)
        if name=='Thinking': bot.rotation_euler.y=.07*math.sin(t); bot.rotation_euler.z=.06*math.sin(t)
        if name=='Greeting': arm.rotation_euler.y=-.45-.35*math.sin(t)
        for obj, paths in [(bot,('location','rotation_euler')),(arm,('rotation_euler',))]:
            for path in paths: obj.keyframe_insert(data_path=path, frame=frame)
    bpy.context.scene.timeline_markers.new(name, frame=start)

world=bpy.context.scene.world; world.color=(.2,.2,.2)
def area(name,loc,power,size):
    bpy.ops.object.light_add(type='AREA', location=loc); obj=bpy.context.object; obj.name=name
    obj.data.energy=power; obj.data.shape='DISK'; obj.data.size=size
    obj.rotation_euler=(Vector((0,0,1.0))-obj.location).to_track_quat('-Z','Y').to_euler()
area('Key',(-3,-4,5),450,4); area('Fill',(3,-2,3),240,3); area('Rim',(1,2,4),380,3)
bpy.ops.object.camera_add(location=(3.0,-8.0,3.1)); cam=bpy.context.object
cam.rotation_euler=(Vector((0,0,1.13))-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.type='ORTHO'; cam.data.ortho_scale=2.7; bpy.context.scene.camera=cam
scene=bpy.context.scene; scene.render.engine='CYCLES'; scene.cycles.samples=16
scene.cycles.use_denoising=True; scene.render.resolution_x=256; scene.render.resolution_y=256
scene.render.resolution_percentage=100; scene.render.film_transparent=True
scene.render.image_settings.file_format='PNG'; scene.frame_start=1; scene.frame_end=75
scene.frame_set(1); bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'cohort_bot.blend'))
scene.render.filepath=str(OUT/'preview.png'); bpy.ops.render.render(write_still=True)
