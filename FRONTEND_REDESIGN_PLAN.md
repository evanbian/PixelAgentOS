# PixelAgentOS 前端重做计划 — Kairosoft 像素办公室风格

## 目标

将当前程序化绘制（Phaser Graphics API 画圆+矩形）的前端，改造为 Kairosoft《游戏发展国》风格的像素艺术办公室。参考项目：[Star-Office-UI](https://github.com/ringhyacinth/Star-Office-UI)。

## 核心体验

- 一间像素风办公室，有真实的办公桌、椅子、电脑、植物
- Agent 是像素小人，坐在工位上办公，有 idle/working/thinking 动画
- PM 作为老板，坐在独立的大办公桌前
- 白板（Whiteboard）：显示任务生命周期和每个 agent 的阶段交付物
- 归档文件柜（Filing Cabinet）：记录每个任务的最终交付物
- 整体 UI 统一像素风（字体、按钮、面板边框）

---

## 架构决策

### 1. 俯视（Top-down）而非等距（Isometric）

理由：
- 当前已有 24×18 的 32px 网格，俯视可以直接复用
- 等距需要 z-order 排序、斜向碰撞、sprite 角度翻倍，复杂度高 2-3 倍
- 《游戏发展国》本身也是略带透视感的俯视角，不是严格等距
- Star-Office-UI 也是俯视，效果很好

### 2. 整体背景图 + 动态 sprite 层（参考 Star-Office-UI 方案）

Star-Office-UI 的做法值得借鉴：**办公室背景是一整张预渲染的图片**，不用 tilemap 拼接。然后在固定坐标上放置动态 sprite（角色动画、家具动画）。

理由：
- 一张精心绘制的背景图比 tilemap 拼接效果好得多（更自然、更有手感）
- 大幅减少开发工作量（不需要 Tiled 编辑器、tileset 制作、图层管理）
- 对美术素材质量要求更可控（一张图 vs 几十个 tile）
- 动态元素（agent、动画家具）仍用 Phaser sprite 覆盖在上层

### 3. Spritesheet 动画系统

- Agent 角色：spritesheet + Phaser Animation Manager
- 状态映射：idle → 坐着呼吸、working → 打字、thinking → 摸下巴、communicating → 说话
- 用颜色变体区分不同 agent（调色板 swap 或 8 套独立 sprite）

### 4. 交互物件 = Phaser 隐形热区 + React Modal

- 白板、文件柜是背景图的一部分（静态绘制在背景上）
- 在对应坐标放 Phaser 隐形点击热区
- 点击 → GameBridge 事件 → React Modal 弹出
- 这和当前的 Task Board 实现方式完全一致，无需新架构

### 5. 保持现有 React 面板不变

- TaskDashboard、AgentDetailPanel、DeliverableViewer、InteractionLog 等全部保留
- 新增 WhiteboardModal 和 FilingCabinetModal
- Zustand store 结构不变，WebSocket 集成不变

---

## 实施分 5 个阶段

### Phase 0: 素材准备（需要用户配合生成）

这是前置依赖，所有后续阶段都需要这些素材。

#### 需要的素材清单：

**A. 办公室背景图（1 张）**
- 尺寸：768×576px（当前 Phaser 画布尺寸）
- 内容：俯视角像素风办公室全景
- 布局要求：
  ```
  ┌──────────────────────────────────────────────────┐
  │  窗户  窗户  窗户        窗户  窗户  窗户  窗户   │  ← 墙壁+窗户
  │                                                  │
  │  [工位1] [工位2] [工位3]     ┌──白板──┐           │  ← 工位区（左半）+ 白板（右上）
  │  [工位4] [工位5] [工位6]     │        │           │
  │                              └────────┘           │
  │  [工位7] [工位8] [工位9]     [PM大桌]              │  ← PM 专属区（右中）
  │                              [PM椅子]              │
  │  [工位10][工位11][工位12]                           │
  │                           [文件柜] [饮水机]        │  ← 文件柜（右下）
  │  🌿          过道              🌿                  │
  │              [门]                                  │  ← 入口
  └──────────────────────────────────────────────────┘
  ```
- 风格：Kairosoft 《游戏发展国》风格，暖色调木地板，浅色墙壁
- 工位上画好桌子+显示器+椅子（静态部分），agent 小人会动态叠加在上面
- 白板上可以有一些装饰性线条（实际内容由 React Modal 展示）
- 文件柜是 2-3 层抽屉的金属柜
- 注意：**工位的椅子位置需要留空给 agent sprite**，桌子和显示器画好

**B. Agent 角色 spritesheet（1 张包含所有变体）**
- 尺寸：256×320px（8 个颜色变体 × 5 个动画状态 × 每状态 4 帧）
- 每帧尺寸：32×32px
- 布局：
  ```
  行 0: Agent 0 (蓝色)   idle(4帧) working(4帧)  = 8列×1行
  行 1: Agent 0 (蓝色)   thinking(4帧) talking(4帧)
  行 2: Agent 1 (绿色)   idle(4帧) working(4帧)
  行 3: Agent 1 (绿色)   thinking(4帧) talking(4帧)
  行 4: Agent 2 (橙色)   ...
  ...（共 8 个颜色变体，每个 2 行）
  行 14: Agent 7 (黄色)  idle(4帧) working(4帧)
  行 15: Agent 7 (黄色)  thinking(4帧) talking(4帧)
  ```
- 或者更简单的方案：**做 1 个灰度基础 sprite，运行时用 Phaser tint 着色**
  - 只需 2 行：idle(4帧) working(4帧) / thinking(4帧) talking(4帧)
  - 尺寸：256×64px
  - Phaser 运行时 `sprite.setTint(0x4fc3f7)` 着色
- 风格：Q 版像素小人，正面偏俯视角，能看到头顶和肩膀
- 每帧动画差异要明显（idle 有轻微摇摆，working 有手部动作）

**C. PM 老板 spritesheet（1 张）**
- 尺寸：256×64px（同上格式，但角色造型不同）
- 与普通 agent 区分：西装/领带、更大的椅子、或头顶有皇冠/星星
- 动画状态同上

**D. 气泡/表情 spritesheet（1 张）**
- 尺寸：128×16px（8 个 16×16 图标）
- 内容：💭思考泡泡、💬对话泡泡、❗惊讶、❓疑问、✅完成、💤休眠、⚡工作中、❌错误
- 用于浮在 agent 头顶显示状态

**E. 像素字体（1 个字体文件）**
- 推荐：[Ark Pixel Font](https://github.com/TakWolf/ark-pixel-font)（Star-Office-UI 也用的这个，支持中文）
- 备选：Press Start 2P（仅英文）
- 12px 或 16px 版本

#### 素材生成方法

用 视觉 LLM 生成时的 prompt 建议：

**背景图 prompt**:
```
Top-down pixel art office room, 768x576 pixels, Kairosoft Game Dev Story style.
Warm wooden floor, light beige walls with windows on top.
Left side: 12 workstations in 4 rows x 3 columns, each with desk, monitor, and chair.
Right top: whiteboard on wall. Right middle: large boss desk with premium chair.
Right bottom: metal filing cabinet and water cooler.
Plants in corners, door at bottom center.
Cute retro 16-bit style, warm color palette, clean pixel art, no anti-aliasing.
```

**角色 sprite prompt**:
```
Pixel art character spritesheet, 32x32 per frame, 8 frames wide, 2 rows.
Top-down office worker, cute chibi style like Kairosoft games.
Row 1: 4 frames idle (slight sway) + 4 frames typing at desk.
Row 2: 4 frames thinking (hand on chin) + 4 frames talking (mouth open).
Grayscale base (will be tinted with color at runtime).
No anti-aliasing, clean pixel art, transparent background.
```

---

### Phase 1: 背景图 + 基础搭建（替换程序化地板）

**改动文件**：
- `OfficeScene.ts` — 删除 `_buildOfficeFloor()` 和 `_buildDecorations()` 的程序化绘制，改为加载背景图
- `config.ts` — 增加背景图路径常量

**具体改动**：

1. `OfficeScene.preload()` 加载背景图：
```typescript
this.load.image('office-bg', '/assets/bg/office_bg.png');
```

2. `OfficeScene.create()` 中替换地板绘制：
```typescript
// 替换 _buildOfficeFloor() + _buildDecorations()
this.add.image(GAME_WIDTH / 2, GAME_HEIGHT / 2, 'office-bg').setOrigin(0.5);
```

3. `_buildWorkstations()` 保留隐形热区逻辑，删除矩形绘制和 emoji：
```typescript
// 删掉 this.add.rectangle(cx, cy, w-4, h-4, 0x2d3561)
// 删掉 this.add.text(cx, cy-4, '🖥️', ...)
// 只保留隐形 hit zone + click handler
```

4. `_buildTaskBoard()` 同理：删除程序化的软木板绘制，只保留隐形热区 + task count 文字 + 点击事件

**新增**：白板和文件柜的隐形热区
```typescript
private _buildInteractiveZones() {
  // 白板热区（坐标对应背景图中白板位置）
  const whiteboardHit = this.add.rectangle(WB_X, WB_Y, WB_W, WB_H, 0xffffff, 0)
    .setInteractive({ cursor: 'pointer' });
  whiteboardHit.on('pointerdown', () => {
    GameBridge.emit(BRIDGE_EVENTS.WHITEBOARD_CLICKED, {});
  });

  // 文件柜热区
  const cabinetHit = this.add.rectangle(FC_X, FC_Y, FC_W, FC_H, 0xffffff, 0)
    .setInteractive({ cursor: 'pointer' });
  cabinetHit.on('pointerdown', () => {
    GameBridge.emit(BRIDGE_EVENTS.FILING_CABINET_CLICKED, {});
  });
}
```

**验收标准**：
- 背景图正确显示，填满 768×576 画布
- 工位区域可点击（沿用现有逻辑）
- 白板和文件柜区域可点击（暂时只 console.log）
- 植物、装饰等已包含在背景图中，无需额外绘制

---

### Phase 2: Agent 像素角色 + 动画系统

**改动文件**：
- `AgentSprite.ts` — 大幅重写，从 Container+Circle 改为 Sprite+Animation
- 新增 `animationConfig.ts`
- `OfficeScene.ts` — preload sprite atlas，update loop 调用动画

**AgentSprite.ts 重写核心**：

```typescript
export class AgentSprite extends Phaser.GameObjects.Container {
  private character: Phaser.GameObjects.Sprite;    // 替代 bodyCircle
  private emoteSprite: Phaser.GameObjects.Sprite;  // 替代 statusRing
  private nameLabel: Phaser.GameObjects.Text;       // 保留
  private bubbleText?: Phaser.GameObjects.Text;     // 保留

  constructor(scene, x, y, agentId, name, avatarIndex, role) {
    super(scene, x, y);

    // 像素角色 sprite（使用 tint 着色方案）
    this.character = scene.add.sprite(0, 0, 'agent-sprites', 'idle_0');
    this.character.setTint(AGENT_COLORS[avatarIndex % AGENT_COLORS.length]);
    this.character.play('agent_idle');
    this.add(this.character);

    // 表情气泡（默认隐藏）
    this.emoteSprite = scene.add.sprite(0, -20, 'emotes', 'none');
    this.emoteSprite.setVisible(false);
    this.add(this.emoteSprite);

    // 名字标签（像素字体）
    this.nameLabel = scene.add.text(0, 14, name, {
      fontFamily: 'ark-pixel',
      fontSize: '10px',
      color: '#ffffff',
    }).setOrigin(0.5);
    this.add(this.nameLabel);
  }

  setStatus(status: AgentStatus) {
    this.currentStatus = status;
    const animKey = STATUS_TO_ANIM[status]; // idle→agent_idle, working→agent_working...
    this.character.play(animKey, true);
    this._showStatusEmote(status);
  }
}
```

**动画注册**（在 OfficeScene.create 中）：
```typescript
// 基于 spritesheet 帧号创建动画
this.anims.create({
  key: 'agent_idle',
  frames: this.anims.generateFrameNumbers('agent-sprites', { start: 0, end: 3 }),
  frameRate: 4,
  repeat: -1,
});
this.anims.create({
  key: 'agent_working',
  frames: this.anims.generateFrameNumbers('agent-sprites', { start: 4, end: 7 }),
  frameRate: 6,
  repeat: -1,
});
// ... thinking, talking
```

**验收标准**：
- Agent 显示为像素小人而非彩色圆圈
- 不同 agent 有不同颜色
- idle/working/thinking 状态有不同动画
- 状态切换时动画平滑过渡
- 头顶有对应状态的气泡图标

---

### Phase 3: PM 老板专属区域 + 白板/文件柜 Modal

**改动文件**：
- `OfficeScene.ts` — PM 检测 & 特殊定位
- `GameBridge.ts` — 新增 FILING_CABINET_CLICKED 事件
- 新增 `WhiteboardModal.tsx`
- 新增 `FilingCabinetModal.tsx`
- `App.tsx` — 挂载新 Modal

**PM 特殊处理**：
```typescript
private _spawnAgent(agent: Agent) {
  // PM 检测：检查 role 或 name
  const isPM = agent.role?.toLowerCase().includes('pm') ||
               agent.name?.toLowerCase().includes('pm');

  if (isPM) {
    // PM 固定坐标（背景图中 PM 大桌位置）
    const sprite = new AgentSprite(this, PM_DESK_X, PM_DESK_Y,
      agent.id, agent.name, agent.avatar_index, agent.role);
    sprite.setAsBoss(true); // 使用 PM sprite + 金色 tint
    // ... 不占用普通工位
  } else {
    // 普通 agent 照旧
  }
}
```

**WhiteboardModal.tsx** — 任务生命周期看板：
```tsx
// 三列看板：待处理 | 进行中 | 已完成
// 每个任务卡片显示：标题、子任务进度条、分配的 agent 头像
// 实时更新（Zustand 订阅）
// 点击卡片展开子任务详情（每个 subtask 的状态 + agent + 阶段交付物摘要）
```

**FilingCabinetModal.tsx** — 归档交付物：
```tsx
// 已完成任务列表，按时间倒序
// 每个任务显示：标题、完成时间、参与 agent、输出摘要
// 点击 → 打开已有的 DeliverableViewer（复用）
// 分页加载（每页 10 个）
```

**验收标准**：
- PM agent 自动坐在大桌前，视觉上有区分
- 点击白板 → WhiteboardModal 弹出，显示所有任务的看板视图
- 点击文件柜 → FilingCabinetModal 弹出，显示历史交付物
- Modal 可通过 Esc/点击外部关闭

---

### Phase 4: 像素风 UI 统一

**改动文件**：
- `App.css` — 全局像素风样式
- `index.html` — 加载像素字体
- 所有 React 组件样式微调

**全局样式改动**：

```css
/* 像素字体 */
@font-face {
  font-family: 'ark-pixel';
  src: url('/assets/fonts/ark-pixel-12px-proportional-zh_cn.ttf.woff2') format('woff2');
}

/* 全局应用 */
body {
  font-family: 'ark-pixel', 'Press Start 2P', monospace;
  image-rendering: pixelated;
}

/* 像素风面板 */
.panel, .modal-content, .status-bar {
  border: 3px solid #4a5590;
  box-shadow: inset 0 0 0 1px #6a7db0, 3px 3px 0 rgba(0,0,0,0.4);
  background: linear-gradient(180deg, #2d3561 0%, #1e2438 100%);
  border-radius: 0; /* 无圆角 — 像素风 */
}

/* 像素按钮 */
.pixel-btn {
  background: #4a5590;
  border: 2px solid #2a3050;
  box-shadow: 2px 2px 0 rgba(0,0,0,0.5), inset 1px 1px 0 #6a7db0;
  color: #fff;
  font-family: inherit;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 0;
}
.pixel-btn:hover { background: #5a65a0; }
.pixel-btn:active {
  box-shadow: inset 2px 2px 0 rgba(0,0,0,0.5);
  transform: translate(1px, 1px);
}
```

**验收标准**：
- 全局字体切换为像素字体（中英文）
- 所有面板/Modal 有统一的像素风边框
- 按钮有按下效果
- 状态栏高度适配像素字体（可能需要调大）

---

### Phase 5: 交互动画增强 + 打磨

**改动文件**：
- `OfficeScene.ts` — 通信动画升级
- `AgentSprite.ts` — 表情系统完善

**通信动画升级**：
```typescript
// 替换当前的虚线 → 使用弧形动画箭头
private _showCommunicationBeam(fromName, toName) {
  // 发送方头顶出现💬气泡
  fromSprite.showEmote('talking');

  // 一个小信封/纸飞机从 from 飞向 to（Phaser tween 路径动画）
  const envelope = this.add.sprite(fromX, fromY, 'emotes', 'message');
  this.tweens.add({
    targets: envelope,
    x: toX, y: toY,
    duration: 600,
    ease: 'Quad.easeInOut',
    onComplete: () => {
      envelope.destroy();
      toSprite.showEmote('reading'); // 接收方显示阅读气泡
    },
  });
}
```

**Agent 入场动画**：
```typescript
// 替换当前的缩放弹出 → 从门口走到工位
private _spawnAgent(agent) {
  // agent 先出现在门口位置
  const sprite = new AgentSprite(this, DOOR_X, DOOR_Y, ...);
  sprite.character.play('agent_walking');

  // tween 移动到目标工位
  this.tweens.add({
    targets: sprite,
    x: targetX, y: targetY,
    duration: 800,
    ease: 'Quad.easeOut',
    onComplete: () => {
      sprite.character.play('agent_idle');
    },
  });
}
```

**验收标准**：
- Agent 入场从门口走到工位（而非凭空出现）
- Agent 间通信有飞行动画
- 表情气泡自动消失（0.5s 显示 + 0.3s 淡出）
- 整体 60fps 流畅运行

---

## 工期估算

| 阶段 | 工作量 | 前置依赖 |
|------|--------|---------|
| Phase 0: 素材准备 | 用户配合，1-2 小时 | 无 |
| Phase 1: 背景图 + 基础搭建 | 2-3 小时 | Phase 0 |
| Phase 2: Agent 像素角色 | 3-4 小时 | Phase 0 |
| Phase 3: PM + Modal | 2-3 小时 | Phase 1 |
| Phase 4: UI 统一 | 1-2 小时 | Phase 1 |
| Phase 5: 动画打磨 | 2-3 小时 | Phase 2 |

Phase 1 和 Phase 2 可以并行。Phase 3、4、5 也可以并行。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| 背景图坐标与 Phaser 热区不对齐 | 做一个 debug 模式显示热区边框，微调坐标常量 |
| 像素字体在小尺寸下不清晰 | 测试 10px/12px/14px，选择最佳尺寸 |
| spritesheet 帧索引错误 | 在 preload 后 console.log 帧数据验证 |
| tint 着色效果不理想 | 备选：为每个 agent 颜色单独绘制 sprite |
| 背景图与 sprite 风格不统一 | 生成素材时使用相同的 prompt 关键词，保持一致的色彩和像素密度 |
| 中文像素字体渲染问题 | Ark Pixel Font 原生支持中日韩，Star-Office-UI 已验证可行 |

---

## 不变的部分（明确列出）

以下内容完全不动：
- 整个 backend（Python FastAPI + WebSocket）
- Zustand store 结构和所有 actions
- WebSocket hook（useWebSocket.ts）
- GameBridge 事件总线（只新增事件，不改现有事件）
- 现有 React 组件：TaskDashboard、AgentDetailPanel、DeliverableViewer、InteractionLog、AgentCreateModal、PMSettings
- REST API 调用
- 数据库 schema
