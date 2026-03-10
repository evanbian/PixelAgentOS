# PixelAgentOS 全套素材生成 Prompt

> 设计原则：**所有素材使用同一个 LLM 生成，共享风格锚定段落，确保视觉一致性。**

---

## 0. 风格锚定（所有 prompt 都必须包含这段）

以下这段文字是**风格基底**，后面每个素材的 prompt 都会在开头引用它。
调通背景图后，请截图保存，后续角色生成时附上背景截图作为 style reference。

```
STYLE ANCHOR (apply to ALL assets):
- Art style: Kairosoft "Game Dev Story" pixel art. Cute, warm, retro 16-bit RPG aesthetic.
- Perspective: Top-down with ~30° frontal tilt (can see character faces and tops of furniture).
- Pixel density: Clean hand-placed pixels, 1px = 1px, NO anti-aliasing, NO sub-pixel blending, NO blur.
- Color palette: Warm tones — honey wood floors, cream/beige walls, soft shadows.
  Accent colors are saturated but not neon. Shadow color is a darker shade of the base, never pure black fill.
- Outlines: 1px dark outlines on all objects and characters (outline color = darkened base color, not always #000000).
- Lighting: Soft top-left light source, subtle highlights on upper-left edges of objects.
- Scale reference: A desk is ~60px wide, a chair is ~25px wide, a character head is ~12-14px diameter.
```

---

## 1. 办公室背景图（最关键，先生成这个）

### 技术规格
- 尺寸：**768 × 576 px**
- 格式：PNG (RGB, no alpha needed)
- 用途：Phaser 游戏的全屏静态背景

### Prompt

```
[STYLE ANCHOR — paste the full style anchor text above here]

TASK: Generate a top-down pixel art office room background image. Size exactly 768 x 576 pixels.

ROOM STRUCTURE:
- Floor: Warm honey-toned wooden plank floor covering the entire room. Planks run horizontally,
  with subtle color variation between planks (alternating slightly lighter/darker strips, ~8px per plank).
- Walls: Top wall and right wall visible. Cream/light beige color with a thin dark baseboard at the bottom edge.
- Top wall: 6 large windows in a row (spanning x=30 to x=420), each ~55px wide with 8px gaps.
  Windows show a blurry pastel cityscape (light blue sky, simple building silhouettes).
  Window frames are light brown wood.
- There are NO left or bottom walls visible (the camera "crops" them off-screen).

EMPLOYEE WORKSTATION AREA (left 55% of the room, x=30 to x=410):
- 12 workstations arranged in a 3-column × 4-row grid.
- Column centers at x ≈ 95, 220, 345. Row centers at y ≈ 130, 250, 370, 490.
- Each workstation consists of ONLY:
  • A wooden desk (~60px wide × 28px deep), warm brown color matching floor tone.
  • A CRT-style monitor on the desk (~20px wide × 18px tall), with a colorful screen glow.
  • A small keyboard in front of the monitor (~16px wide).
  • IMPORTANT: **NO chairs at employee workstations.** The chair space (below/south of desk)
    must be EMPTY FLOOR. Characters with their own chairs will be overlaid dynamically.
- Desks in the same row are aligned horizontally. Leave ~40px vertical gap between rows for the
  empty chair space where character sprites will be placed.
- Each monitor screen can show a different color (green, blue, amber, white) for visual variety.

PM / BOSS AREA (right side, x=480 to x=700, y=280 to y=400):
- One large executive desk (~120px wide × 50px deep), darker wood tone than employee desks.
- A laptop (open, ~18px) and a few documents/papers on the desk.
- A small "BOSS" nameplate on the front edge of the desk.
- **NO chair here either** — the PM character sprite will include their own executive chair.
- Slightly elevated/distinguished from the employee area (maybe a subtle rug or different floor shade underneath).

WHITEBOARD (right side, x=470 to x=660, y=80 to y=220):
- A large whiteboard mounted on the wall (~190px wide × 130px tall).
- White surface with a thin aluminum/grey frame.
- A few colorful sticky notes (yellow, pink, blue, green) arranged on it — these are decorative.
- A small shelf at the bottom with 2-3 marker pens.

BOOKSHELF (far right, x=680 to x=750, y=80 to y=250):
- A tall wooden bookshelf against the right wall (~70px wide × 170px tall).
- 4-5 shelves with colorful book spines (reds, blues, greens, yellows).
- A small plant or trophy on the top shelf.

FILING CABINET (right side, x=500 to x=560, y=460 to y=520):
- A 3-drawer metal filing cabinet, grey/silver color.
- Each drawer has a small handle and a label slot.
- Slightly industrial look contrasting with the warm wood office.

WATER COOLER (right side, x=590 to x=640, y=460 to y=520):
- A standard office water cooler with a blue water jug on top.
- White/light grey body, small spout area.

DOOR (bottom center, x=345 to x=425, y=540 to y=576):
- A wooden office door, slightly darker brown than the desks.
- Small doorknob on the right side.
- Positioned at the bottom edge of the image (partially cut off — we see the top 60% of the door).
- Small "EXIT" sign or room number above the door.

DECORATIVE PLANTS:
- Plant 1: A medium potted plant (bushy green leaves in a grey/white ceramic pot) near top-left corner (x≈30, y≈70).
- Plant 2: A smaller potted plant near the door (x≈440, y≈530).
- Plant 3: A tall narrow plant near the bottom-right corner (x≈720, y≈520).

ADDITIONAL DETAILS:
- A wall clock on the top wall between the windows area and the whiteboard (x≈440, y≈30), round, simple design.
- Subtle floor shadow under each desk (a slightly darker oval on the floor beneath).
- A small trash bin next to the PM desk.
- Thin power cables running from desks to the wall (optional, adds realism).

ABSOLUTELY DO NOT INCLUDE:
- Any chairs (office chairs, stools, etc.) anywhere in the image
- Any human characters or figures
- Any animals or creatures
- Harsh black backgrounds or borders outside the room
```

---

## 2. 角色 Spritesheet — 通用说明

### 技术规格
- 每帧尺寸：**48 × 48 px**
- 背景：**透明**（PNG with alpha channel）
- 每个角色输出：**4 帧横排** = 192 × 48 px（一个动画状态）
- 或一次性输出 **8 帧横排** = 384 × 48 px（两个动画状态）

### 角色设计原则

所有角色共享这些特征：
- Q 版 / Chibi 比例：头占身高的 40%（约 2.5 头身）
- 坐姿：人物坐在一把小型深色办公转椅上（**椅子是角色的一部分**，不在背景里）
- 可见范围：完整角色 — 头、身体、手臂、椅子、脚（如果露出的话）
- 朝向：面朝屏幕下方偏正面（与背景的俯视角匹配）
- 角色整体高度约 36-40px，在 48×48 画布中上下留少量空白
- 椅子：标准黑色办公转椅，带小轮子，约 12px 高（角色坐在上面）

### 每个角色的完整 Prompt 结构

```
[STYLE ANCHOR]

[角色描述 — 见下方各角色]

[动画状态描述 — 见下方各状态]

Technical requirements:
- Canvas: 48x48 pixels per frame, 4 frames in a horizontal strip = 192x48 total.
- Each frame has transparent background (alpha channel).
- Character sits on a small dark office swivel chair with tiny wheels — the chair is PART of the sprite.
- Character faces slightly toward the viewer (front-facing top-down perspective matching the office background).
- Clean pixel art: no anti-aliasing, no blur, no sub-pixel rendering.
- 1px dark outlines on the character and chair.
- Frames must have VISIBLE differences for animation — if the differences are too subtle, the animation won't read.
```

---

## 3. 八个角色 × 四个状态 = 32 个 Prompt

> **生成顺序建议**：先生成 Developer idle → 确认风格满意 → 以此为 reference 生成其他所有。

---

### 角色 A: Developer 💻

**视觉关键词**：蓝色连帽衫、耳机挂脖子、深色乱发、典型程序员

```
CHARACTER: Developer — a young male software developer.
- Hair: Messy short dark brown/black hair, slightly spiky.
- Face: Friendly expression, small round eyes, relaxed look.
- Outfit: Blue hoodie (hood down), the hoodie has a slightly darker blue pocket area.
- Accessory: Black over-ear headphones resting around neck.
- Posture: Slightly hunched forward, the "coder lean".
- Chair: Standard black office swivel chair with small wheels.
```

**Developer × idle**
```
[STYLE ANCHOR]
[DEVELOPER CHARACTER — above]

ANIMATION STATE: idle — relaxed sitting.
4 frames showing a subtle idle breathing cycle:
- Frame 1: Neutral seated pose, hands resting on thighs, looking forward.
- Frame 2: Very slight upward body shift (1-2px rise) as if breathing in, shoulders slightly raised.
- Frame 3: Same as Frame 1 (back to neutral).
- Frame 4: Very slight lean to one side (1px), head tilts slightly — restless coder fidget.
Output: 4 frames in a horizontal strip, 192x48 px, transparent background.
```

**Developer × working**
```
[STYLE ANCHOR]
[DEVELOPER CHARACTER]

ANIMATION STATE: working — actively typing on keyboard.
4 frames showing typing animation:
- Frame 1: Both hands forward at desk level, left hand slightly higher (pressing key).
- Frame 2: Right hand slightly higher, left hand down (alternating keystroke).
- Frame 3: Similar to Frame 1 but body leans 1px more forward (deep focus).
- Frame 4: Similar to Frame 2, slight head dip (reading code on screen).
Hands must show CLEAR vertical movement (3-4px difference between up/down positions).
Output: 4 frames in a horizontal strip, 192x48 px, transparent background.
```

**Developer × thinking**
```
[STYLE ANCHOR]
[DEVELOPER CHARACTER]

ANIMATION STATE: thinking — pondering a problem.
4 frames showing thinking animation:
- Frame 1: Right hand raised to chin, left hand on thigh, looking slightly upward.
- Frame 2: Same pose, head tilts slightly right (1px shift).
- Frame 3: Right hand moves slightly away from chin (2px), as if about to snap fingers.
- Frame 4: Head tilts back to center, hand returns to chin. Slight body lean back.
The "hand on chin" pose must be clear and recognizable even at 48px scale.
Output: 4 frames in a horizontal strip, 192x48 px, transparent background.
```

**Developer × communicating**
```
[STYLE ANCHOR]
[DEVELOPER CHARACTER]

ANIMATION STATE: communicating — talking and gesturing.
4 frames showing speaking animation:
- Frame 1: Mouth open (1px wider than closed), right hand raised at chest level, palm open.
- Frame 2: Mouth closed, hand moved slightly higher and to the right (gesturing).
- Frame 3: Mouth open again, hand back to chest level, slight body lean forward.
- Frame 4: Mouth closed, both hands visible at sides, slight shrug pose.
Mouth open/closed and hand position changes must be clearly visible.
Output: 4 frames in a horizontal strip, 192x48 px, transparent background.
```

---

### 角色 B: Researcher 🔍

**视觉关键词**：白色实验服外套、圆框眼镜、棕色丸子头、女性、学术气质

```
CHARACTER: Researcher — a female academic researcher.
- Hair: Brown hair tied in a neat bun on top of head, a few loose strands framing the face.
- Face: Curious, attentive expression, bright eyes behind round glasses.
- Glasses: Small round wireframe glasses, silver/grey color.
- Outfit: White lab coat over a light blue collared shirt. Lab coat is open in front.
- Accessory: A small pen tucked behind ear (optional, if visible at this scale).
- Posture: Upright, good posture, attentive and alert.
- Chair: Standard black office swivel chair with small wheels.
```

**Researcher × idle / working / thinking / communicating**：沿用上面相同的 4 个动画状态描述，只替换角色段落为 Researcher。

---

### 角色 C: Analyst 📊

**视觉关键词**：灰色马甲、领带、方框眼镜、整洁短发、男性、商务风

```
CHARACTER: Analyst — a male data analyst, business casual style.
- Hair: Short neat black hair, side-parted, well-groomed.
- Face: Focused, slightly serious expression, thin-framed rectangular glasses.
- Glasses: Small rectangular glasses, dark frame.
- Outfit: Light grey vest over white dress shirt, dark blue tie. Sleeves rolled up to elbows.
- Posture: Precise, upright, methodical body language.
- Chair: Standard black office swivel chair with small wheels.
```

---

### 角色 D: Writer ✍️

**视觉关键词**：深绿开衫、奶油色高领内搭、波浪红棕色长发、女性、文艺气质

```
CHARACTER: Writer — a female content writer with a creative, literary vibe.
- Hair: Wavy auburn/reddish-brown hair falling past shoulders, slightly tousled.
- Face: Warm, thoughtful expression, gentle smile when idle.
- Outfit: Dark green knit cardigan over a cream/off-white turtleneck. The cardigan is unbuttoned.
- Accessory: A small hair clip or headband (simple, not flashy).
- Posture: Relaxed, slightly leaning — the "writer's slouch", comfortable.
- Chair: Standard black office swivel chair with small wheels.
```

---

### 角色 E: Designer 🎨

**视觉关键词**：黑色高领衫、粉紫色挑染短发、小耳环、女性、潮流创意风

```
CHARACTER: Designer — a female creative designer, trendy appearance.
- Hair: Short bob haircut with pink-purple highlights/tips, base color is dark. Eye-catching hair color.
- Face: Expressive, confident look, slightly arched eyebrows.
- Outfit: Black turtleneck (Steve Jobs/designer classic), sleek and minimal.
- Accessory: A small colorful earring or stud (just 1-2 bright pixels to suggest it).
- Posture: Relaxed but dynamic, creative energy — slightly more animated than others even when idle.
- Chair: Standard black office swivel chair with small wheels.
```

---

### 角色 F: PM 📋（项目经理/老板）

**视觉关键词**：深蓝西装、红色领带、整齐深色发、金色徽章、男性、权威感、**高级转椅**

```
CHARACTER: PM (Project Manager) — the boss, male, authoritative but approachable.
- Hair: Neatly combed dark hair with a hint of grey at the temples, professional look.
- Face: Confident slight smile, mature expression, small but visible jawline.
- Outfit: Dark navy blue suit jacket over white shirt, red/crimson tie. Suit is well-fitted.
- Accessory: A tiny gold star pin on the suit lapel (just 2-3 bright yellow pixels).
- Posture: Upright, broad shoulders, commanding but not stiff.
- Chair: **EXECUTIVE leather chair** — larger and darker brown/black than regular office chairs,
  with visible armrests and a taller back. This chair should be noticeably different from the
  standard black swivel chairs used by other characters (~30% wider, higher back).
```

---

### 角色 G: DevOps 🔧

**视觉关键词**：深色毛线帽、灰色 T 恤（齿轮图标）、略带胡茬、男性、休闲运维风

```
CHARACTER: DevOps Engineer — a male ops/infrastructure specialist, casual tech style.
- Hair: Partially hidden under a dark navy/charcoal beanie/knit cap. Light brown hair visible at sides.
- Face: Relaxed, slightly tired but competent look, subtle stubble (1-2 darker pixels on jaw).
- Outfit: Dark grey t-shirt with a small bright green terminal cursor or gear icon on chest
  (just 3-4 pixels of accent color). Casual, not dressed up.
- Posture: Laid-back in the chair, relaxed lean, one arm might rest on the chair armrest.
- Chair: Standard black office swivel chair with small wheels.
```

---

### 角色 H: QA 🧪

**视觉关键词**：护目镜推额头上、齐刘海黑直发、浅紫色 Polo 衫、女性、严谨测试风

```
CHARACTER: QA Engineer — a female quality assurance tester, precise and methodical.
- Hair: Straight black hair with neat bangs, shoulder length, clean-cut appearance.
- Face: Alert, detail-oriented expression, eyes slightly narrowed (looking for bugs!).
- Outfit: Light purple/lavender polo shirt, clean and neat. Simple and professional.
- Accessory: Safety goggles pushed up onto forehead (resting on top of head) — a quirky QA trait.
  The goggles are orange/amber colored, ~8px wide across the forehead area.
- Posture: Leaning slightly forward, the "inspector lean" — actively examining things.
- Chair: Standard black office swivel chair with small wheels.
```

---

## 4. 四个动画状态（通用模板）

> 每个角色都要生成下面 4 个状态。将角色描述段落 + 状态描述 + 技术要求组合成完整 prompt。

### State 1: idle（待机）

```
ANIMATION STATE: idle — relaxed sitting, waiting for work.
4 frames of subtle breathing/fidget cycle:
- Frame 1: Neutral seated pose, hands resting naturally, looking forward at screen area.
- Frame 2: Very slight upward body shift (1-2px) — breathing in, shoulders rise slightly.
- Frame 3: Return to neutral position.
- Frame 4: Tiny side lean or head tilt (1px) — natural micro-fidget.
Movement is MINIMAL but must be perceptible. This is a calm, relaxed loop.
```

### State 2: working（工作中）

```
ANIMATION STATE: working — actively typing/working at the desk.
4 frames of typing animation:
- Frame 1: Both hands extended forward at desk level. Left hand up (pressing key), right hand down.
- Frame 2: Hands swap — right hand up, left hand down. Clear alternating motion.
- Frame 3: Similar to Frame 1, body leans 1px forward (deep concentration).
- Frame 4: Similar to Frame 2, slight head dip toward screen.
Hand movement must be OBVIOUS — at least 3-4px vertical difference between "hand up" and "hand down".
This is the most active animation. The character should look busy and focused.
```

### State 3: thinking（思考中）

```
ANIMATION STATE: thinking — pondering, problem-solving.
4 frames of thinking animation:
- Frame 1: One hand raised to chin/cheek, supporting head. Other hand on lap. Looking slightly upward.
- Frame 2: Head tilts slightly to one side (1px horizontal shift). Same hand-on-chin pose.
- Frame 3: Hand moves slightly away from chin (2px), as if having a thought. Head shifts back.
- Frame 4: Hand returns to chin. Slight lean backward in chair.
The "hand on chin" must be the dominant visual feature of this state.
Character appears lost in thought, staring slightly upward.
```

### State 4: communicating（交流中）

```
ANIMATION STATE: communicating — talking, explaining, discussing.
4 frames of speaking/gesturing animation:
- Frame 1: Mouth open (visible 1px gap), one hand raised with open palm at chest level.
- Frame 2: Mouth closed, hand moves higher and slightly outward (mid-gesture).
- Frame 3: Mouth open again, hand moves back to chest level, slight forward lean (emphasis).
- Frame 4: Mouth closed, hand lowers, body returns to neutral — brief pause in speech.
Mouth changes and hand gestures must be clearly visible.
This should look distinctly different from "working" — arms are more outward/upward, not forward at desk.
```

---

## 5. 表情气泡 Spritesheet（可选，优先级低）

```
[STYLE ANCHOR]

TASK: Generate a row of 8 small pixel art status icons/emotes, each 16x16 pixels.
Total output: 128 x 16 px horizontal strip, transparent background.

The 8 icons (left to right):
1. 💭 Thought bubble: white cloud shape with "..." inside, classic comic thought bubble.
2. 💬 Speech bubble: white rounded rectangle with "..." inside, small triangle tail pointing down.
3. ❗ Alert: red exclamation mark on a tiny yellow triangle — warning/attention.
4. ❓ Question: blue question mark, slightly stylized.
5. ✅ Checkmark: green checkmark in a small circle — task complete.
6. 💤 Sleep: two small blue "Z" letters stacked — idle/dormant.
7. ⚡ Lightning bolt: yellow/orange zigzag bolt — working/active.
8. ❌ Error: red "X" mark — error/failed state.

Style: Clean pixel art matching the Kairosoft office theme.
Each icon must be recognizable at 16x16 scale — keep shapes simple and bold.
No anti-aliasing, transparent background.
```

---

## 6. 生成工作流

### 步骤

```
Step 1: 生成背景图
  → 用第 1 节的完整 prompt
  → 确认：768×576、无椅子、布局合理
  → 保存为 office_bg.png

Step 2: 生成风格锚定角色（Developer idle）
  → 用 Developer 角色描述 + idle 状态 + 技术要求
  → 附上 Step 1 的背景图作为风格参考
  → 确认：48×48、透明背景、含椅子、像素干净
  → 这个结果就是后续所有角色的 style reference

Step 3: 批量生成所有角色的所有状态
  → 每次生成时附上 Step 2 的结果作为 style reference
  → 生成顺序：每个角色的 4 个状态连续生成（保持角色一致性）
  → Developer(idle→working→thinking→communicating)
  → Researcher(idle→working→thinking→communicating)
  → ... 依次类推

Step 4: 生成表情气泡（可选）

Step 5: 交付所有 PNG 文件
  → 我用 Python 脚本合并成最终 spritesheet
  → 更新前端代码（config.ts + AgentSprite.ts）
  → 重新校准坐标
```

### 文件命名规范

```
背景:
  office_bg.png                (768×576)

角色（每个文件 192×48，4帧横排）:
  developer_idle.png
  developer_working.png
  developer_thinking.png
  developer_communicating.png
  researcher_idle.png
  researcher_working.png
  ...
  qa_communicating.png

表情:
  emotes.png                   (128×16)
```

---

## 7. 质量检查清单

每个素材检查：

- [ ] **尺寸正确**：背景 768×576，角色帧 48×48（或 4 帧 192×48）
- [ ] **背景无椅子**：12 个工位只有桌子+显示器，绝无椅子
- [ ] **角色含椅子**：每个角色精灵包含人物 + 脚下的办公转椅
- [ ] **透明背景**：角色 PNG 背景是透明的，不是白色或灰色
- [ ] **无反锯齿**：边缘像素锐利，无模糊半透明过渡
- [ ] **动画差异明显**：4 帧之间手/头/身体有清晰的位置变化
- [ ] **角色可区分**：每个角色有独特的发型+服装+配饰
- [ ] **风格统一**：所有角色与背景的颜色饱和度、轮廓风格一致
- [ ] **PM 区分度**：PM 的椅子明显比其他角色大/豪华
- [ ] **比例一致**：所有角色的头身比、椅子大小保持一致（PM椅子除外）

---

## 8. 提示：常见问题与解决

| 问题 | 解决方案 |
|------|---------|
| LLM 生成了椅子在背景图里 | 在 prompt 末尾加粗强调 "ABSOLUTELY NO CHAIRS" |
| 角色背景不透明 | 明确要求 "transparent background (alpha channel)"，检查 PNG 模式 |
| 每帧动画差异太小 | 增大描述中的像素差异值（如 "3-4px" 改为 "5-6px"） |
| 角色风格不统一 | 始终附上 Step 2 的参考图，提高 reference strength |
| 尺寸不精确 | 大多数 LLM 无法精确控制像素尺寸，生成后用 Python resize (nearest neighbor) |
| 出现反锯齿 | 加 "absolutely no anti-aliasing, no smoothing, crisp pixel edges" |
| 椅子和人物比例不对 | 椅子占帧高度约 25-30%（12-14px），人物占 70-75%（34-36px） |
