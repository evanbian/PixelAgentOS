# PixelAgentOS 角色素材生成指南

## 一、总体规格

| 参数 | 值 |
|------|-----|
| 单帧尺寸 | 48×48 px |
| 角色数量 | 8 个（按 Role 区分外观） |
| 动画状态 | 4 个（idle / working / thinking / communicating） |
| 每状态帧数 | 4 帧 |
| 最终 spritesheet | 384×768 px（8列 × 16行） |
| 背景 | **透明**（PNG with alpha） |
| 禁止包含 | 椅子、桌子、显示器（这些在背景图里已有） |

## 二、背景参考

当前办公室背景风格：
- **Kairosoft《游戏发展国》** 像素风
- 暖色木地板（RGB ≈ 134, 96, 59）
- 深色办公椅（RGB ≈ 102, 71, 48）
- 棕色桌面 + CRT 风格显示器
- 略带透视的俯视角（能看到角色头顶和正面）

**角色在画面中的位置**：坐在椅子上，头部在桌面与椅背之间，约 30-35px 高的可见区域。

## 三、风格锚定 Prompt（先生成这个作为 Style Reference）

> **用途**：先用这个 prompt 生成 1 个角色，确认风格满意后，用它作为后续所有角色的 style reference image。

### PixelLab Prompt

```
Pixel art office worker sitting in chair, top-down RPG view with slight perspective.
Cute chibi character, 2.5-head proportion, Kairosoft Game Dev Story style.
Male developer wearing blue hoodie, headphones around neck, messy dark hair.
Character is seated, visible from waist up, arms resting on invisible desk.
Simple clean pixel art, warm color palette, black outline, no anti-aliasing.
Transparent background, NO furniture, NO chair, NO desk - character body only.
48x48 pixel canvas.
```

### 通用 Prompt（适用于 DALL-E / Midjourney / 其他）

```
Pixel art character sprite, 48x48 pixels, transparent background.
Cute chibi office worker in Kairosoft Game Dev Story art style.
Top-down view with slight front-facing angle, 2.5-head proportion body.
Character sitting pose (waist-up visible), arms at desk height.
Clean pixel art, no anti-aliasing, warm tones, thin black outlines.
DO NOT include any furniture, chair, desk, or monitor - only the character.
```

---

## 四、8 个角色的 Prompt

> **重要**：每个角色都要附带 Style Reference，使用步骤三中生成的参考图。
> 在 PixelLab 中选择 "Use Reference Image" → 上传步骤三的图 → 保持风格一致。

### 角色 1: Developer 💻（开发者）

```
Pixel art chibi developer sitting at desk, 48x48, transparent background.
Young male, dark messy hair, wearing blue hoodie with hood down.
Headphones around neck, slightly hunched forward (coding posture).
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：蓝色连帽衫、耳机、深色乱发

### 角色 2: Researcher 🔍（研究员）

```
Pixel art chibi researcher sitting at desk, 48x48, transparent background.
Female, brown hair in neat bun, round glasses, wearing white lab coat over blue shirt.
Holding a small notepad or pen, academic/scholarly appearance.
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：白色实验服、圆框眼镜、棕色丸子头

### 角色 3: Analyst 📊（分析师）

```
Pixel art chibi data analyst sitting at desk, 48x48, transparent background.
Male, short neat black hair, rectangular glasses, wearing grey vest over white shirt with tie.
Professional business appearance, slightly serious expression.
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：灰色马甲、领带、方框眼镜、整洁短发

### 角色 4: Writer ✍️（写手）

```
Pixel art chibi writer sitting at desk, 48x48, transparent background.
Female, wavy auburn/red hair, wearing dark green cardigan over cream turtleneck.
Creative appearance, perhaps a small beret or hair accessory.
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：深绿开衫、波浪红棕色头发、文艺气质

### 角色 5: Designer 🎨（设计师）

```
Pixel art chibi designer sitting at desk, 48x48, transparent background.
Female, short colorful hair (pink or purple highlights), wearing black turtleneck.
Trendy creative appearance, small earring or hair clip accessory.
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：黑色高领衫、粉/紫色挑染短发、潮流感

### 角色 6: PM 📋（项目经理 / 老板）

```
Pixel art chibi project manager / boss sitting at desk, 48x48, transparent background.
Male, neatly combed dark hair with slight grey, wearing navy blue suit with red tie.
Professional authoritative appearance, slight smile, confident posture.
Small golden star or crown pin on lapel to indicate leadership.
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：深蓝西装、红色领带、整齐发型、金色徽章/星星

### 角色 7: DevOps 🔧（运维工程师）

```
Pixel art chibi DevOps engineer sitting at desk, 48x48, transparent background.
Male, wearing dark beanie/cap, grey t-shirt with a small gear/terminal icon.
Casual tech appearance, slight stubble, relaxed posture.
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：深色毛线帽、灰色 T 恤（齿轮图标）、休闲感

### 角色 8: QA 🧪（测试工程师）

```
Pixel art chibi QA engineer sitting at desk, 48x48, transparent background.
Female, straight black hair with bangs, safety goggles pushed up on forehead.
Wearing light purple polo shirt, precise and methodical appearance.
Kairosoft Game Dev Story style, clean pixel art, black outlines.
Top-down RPG perspective, seated pose, waist-up visible.
NO furniture - character only.
```

**视觉特征**：护目镜（推在额头上）、齐刘海黑直发、浅紫色 Polo 衫

---

## 五、4 个动画状态的 Prompt 后缀

> 对每个角色，分别生成 4 个状态。在角色 prompt 后面追加以下状态描述。
> 每个状态需要 **4 帧**的动画序列。

### 状态 1: idle（待机/空闲）

```
Animation: idle sitting pose, 4 frames.
Frame 1-4: subtle breathing motion - slight body rise and fall.
Hands resting on lap or desk edge, relaxed posture.
Very gentle sway, minimal movement, peaceful expression.
```

**动画要点**：轻微呼吸起伏，身体微微摇摆，放松姿态

### 状态 2: working（工作中/打字）

```
Animation: typing at desk, 4 frames.
Frame 1-4: hands moving up and down alternately, simulating keyboard typing.
Focused expression, leaning slightly forward.
Head stays relatively still, arms/hands have clear movement between frames.
```

**动画要点**：双手交替起落（模拟打字），身体微微前倾，专注表情

### 状态 3: thinking（思考中）

```
Animation: thinking pose, 4 frames.
Frame 1-4: one hand raised to chin, slight head tilt.
Thoughtful expression with dot-dot-dot thought bubble feel.
Gentle rocking motion, looking slightly upward.
```

**动画要点**：单手托下巴，头微微歪，略朝上看，若有所思

### 状态 4: communicating（交流中/说话）

```
Animation: talking/speaking pose, 4 frames.
Frame 1-4: mouth opening and closing, one hand gesturing.
Animated expression, slight body movement while speaking.
Hand gestures alternate between raised and lowered positions.
```

**动画要点**：嘴巴开合、单手比划、表情生动、有肢体语言

---

## 六、Spritesheet 组装规格

### 最终布局

每行 8 帧（48px × 8 = 384px），每个角色占 2 行：

```
Row  0: Developer   → idle(4帧) + working(4帧)
Row  1: Developer   → thinking(4帧) + communicating(4帧)
Row  2: Researcher  → idle(4帧) + working(4帧)
Row  3: Researcher  → thinking(4帧) + communicating(4帧)
Row  4: Analyst     → idle(4帧) + working(4帧)
Row  5: Analyst     → thinking(4帧) + communicating(4帧)
Row  6: Writer      → idle(4帧) + working(4帧)
Row  7: Writer      → thinking(4帧) + communicating(4帧)
Row  8: Designer    → idle(4帧) + working(4帧)
Row  9: Designer    → thinking(4帧) + communicating(4帧)
Row 10: PM          → idle(4帧) + working(4帧)
Row 11: PM          → thinking(4帧) + communicating(4帧)
Row 12: DevOps      → idle(4帧) + working(4帧)
Row 13: DevOps      → thinking(4帧) + communicating(4帧)
Row 14: QA          → idle(4帧) + working(4帧)
Row 15: QA          → thinking(4帧) + communicating(4帧)
```

**总尺寸**：384 × 768 px

### 单角色导出命名

如果工具逐个导出，命名建议：
```
developer_idle.png      (4帧横排, 192×48)
developer_working.png   (4帧横排, 192×48)
developer_thinking.png  (4帧横排, 192×48)
developer_talking.png   (4帧横排, 192×48)
researcher_idle.png
...以此类推
```

我会提供 Python 脚本自动合并成最终 spritesheet。

---

## 七、质量检查清单

生成每个素材后，请检查：

- [ ] 背景是否透明（不是白色/灰色）
- [ ] 是否包含家具（椅子/桌子/显示器）→ 如果有，需要重新生成
- [ ] 尺寸是否正确（48×48 或 4 帧横排 192×48）
- [ ] 像素是否干净（无模糊/反锯齿）
- [ ] 角色风格是否与背景图一致（Kairosoft 风格）
- [ ] 4 帧之间是否有明显的动画差异
- [ ] 角色之间是否有明显的外观区分（服装/发型/配饰）

---

## 八、如果使用 PixelLab 的工作流

1. **Step 1**：用「风格锚定 Prompt」生成 Developer 的 idle 帧 → 确认风格满意
2. **Step 2**：将 Step 1 的结果设为 Style Reference
3. **Step 3**：生成 Developer 的 4 个动画状态（每状态 4 帧）
4. **Step 4**：保持同一 Style Reference，逐一生成其余 7 个角色
5. **Step 5**：所有素材导出 → 用合并脚本组装 spritesheet
6. **Step 6**：放入 `frontend/public/assets/sprites/` 并通知我做代码集成

### PixelLab 设置建议

- **Canvas Size**: 48×48
- **Style**: Pixel Art (enable)
- **Anti-aliasing**: OFF
- **Background**: Transparent
- **Reference Strength**: 70-80%（太高会让所有角色长一样）

---

## 九、备选方案：继续使用 Tint 着色（简化版）

如果不想画 8 个不同角色，可以用 **2-3 个基础体型 + tint 着色** 的折中方案：

- 体型 A（男性偏瘦）：Developer, Analyst, DevOps
- 体型 B（女性）：Researcher, Writer, Designer, QA
- 体型 C（男性偏壮）：PM

仍然去掉椅子，用浅色灰度（亮度 180-230）绘制，这样 tint 着色效果会好很多。

这样只需要生成 3 × 4 状态 × 4 帧 = 48 帧素材（而非 128 帧）。
