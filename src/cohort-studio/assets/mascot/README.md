# Cohort Studio mascot

The Blender scene contains an original robot with three timeline ranges:

- Idle: frames 1–25
- Thinking: frames 26–50
- Greeting: frames 51–75
- Idle dance: frames 76–100

Rebuild with Blender, then export the transparent WebP animations with Pillow:

```sh
blender --background --python create_mascot.py
blender --background cohort_bot.blend --python render_animations.py
python export_webp.py
```

The Agent header uses idle and thinking animations, briefly waves after a successful reply, and dances after ten seconds without interaction. WebP animations use 24 frames at approximately 24 frames per second. It shows a still frame when the browser requests reduced motion.
