# A small Cycles scene: two frames of a lit sphere turning, 320x180, 32 samples. It builds everything at render time
# from an empty file, as every scene script does, so it renders the same under any Blender.
# blender -b --factory-startup --python test-scene.py -o OUT/#### -a
import math
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
s = bpy.context.scene
s.render.engine = "CYCLES"
s.cycles.samples = 32
s.render.resolution_x, s.render.resolution_y = 320, 180
s.render.image_settings.file_format = "PNG"
s.frame_start, s.frame_end = 1, 2

bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24)
ball = bpy.context.object
bpy.ops.object.shade_smooth()
mat = bpy.data.materials.new("ball")
mat.use_nodes = True
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.9, 0.35, 0.1, 1)
ball.data.materials.append(mat)
ball.rotation_euler = (0, 0, 0)
ball.keyframe_insert("rotation_euler", frame=1)
ball.rotation_euler = (0, 0, math.pi / 4)
ball.keyframe_insert("rotation_euler", frame=2)

bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, -1))

light = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
light.data.energy = 4
light.rotation_euler = (0.6, 0.2, 0.8)
s.collection.objects.link(light)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.location = (0, -6, 1.5)
cam.rotation_euler = (math.radians(80), 0, 0)
s.collection.objects.link(cam)
s.camera = cam

world = bpy.data.worlds.new("world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.3
s.world = world
