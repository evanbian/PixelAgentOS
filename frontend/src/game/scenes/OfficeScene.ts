import Phaser from 'phaser';
import { AgentSprite } from '../sprites/AgentSprite';
import { GameBridge, BRIDGE_EVENTS } from '../GameBridge';
import {
  GAME_WIDTH,
  GAME_HEIGHT,
  WORKSTATION_POSITIONS,
  INTERACTIVE_ZONES,
  PM_DESK_POSITION,
  ASSETS,
  EMOTE_ASSETS,
  SPRITE_CONFIG,
  DEBUG_HIT_ZONES,
} from '../config';

import type { Agent } from '../../types';
import { useStore } from '../../store/useStore';

// PM-to-normal scale ratio (lazy to avoid TDZ issues with SPRITE_CONFIG)
function getPMScaleRatio(): number {
  return (SPRITE_CONFIG.PM_DISPLAY_SCALE ?? SPRITE_CONFIG.DISPLAY_SCALE) / SPRITE_CONFIG.DISPLAY_SCALE;
}

interface WorkstationData {
  id: string;
  x: number;
  y: number;
}

export class OfficeScene extends Phaser.Scene {
  private workstations = new Map<string, WorkstationData>();
  private agentSprites = new Map<string, AgentSprite>();
  private bridgeUnsubscribers: Array<() => void> = [];
  private storeUnsub?: () => void;

  constructor() {
    super({ key: 'OfficeScene' });
  }

  // ── Preload assets ──────────────────────────────────────────────────────────

  preload() {
    this.load.image('office-bg', ASSETS.BG);
    // Load per-role spritesheets
    for (const [role, path] of Object.entries(ASSETS.ROLE_SPRITES)) {
      this.load.spritesheet(`sprite-${role.toLowerCase()}`, path, {
        frameWidth: SPRITE_CONFIG.FRAME_WIDTH,
        frameHeight: SPRITE_CONFIG.FRAME_HEIGHT,
      });
    }
    // Load Twemoji emote images
    for (const [key, path] of Object.entries(EMOTE_ASSETS)) {
      this.load.image(key, path);
    }
  }

  // ── Create scene ────────────────────────────────────────────────────────────

  create() {
    // 1. Background image
    this.add.image(GAME_WIDTH / 2, GAME_HEIGHT / 2, 'office-bg').setOrigin(0.5);

    // 2. Invisible workstation hit zones (replaces _buildWorkstations visual)
    this._buildWorkstations();

    // 3. Interactive zones: whiteboard, filing cabinet (replaces _buildTaskBoard visual)
    this._buildInteractiveZones();

    // 4. Task count overlay on whiteboard area (lightweight text only)
    this._buildTaskCountOverlay();

    // 5. PM sprite always present at boss desk
    this._spawnPMSprite();

    // 6. Event wiring
    this._setupClickBridge();
    this._setupStoreSubscription();

    // Cleanup handlers
    this.events.on(Phaser.Scenes.Events.SHUTDOWN, this._cleanup, this);
    this.events.on(Phaser.Scenes.Events.DESTROY, this._cleanup, this);
  }

  // ── Store subscription (Zustand → Phaser) ──────────────────────────────────

  private _setupStoreSubscription() {
    // Sync existing agents immediately
    const { agents } = useStore.getState();
    agents.forEach((a) => this._spawnAgent(a));

    // Subscribe to activity feed for agent-to-agent communication animations
    let lastActivityLen = useStore.getState().activityFeed.length;
    const activityUnsub = useStore.subscribe((state) => {
      const feed = state.activityFeed;
      if (feed.length > lastActivityLen) {
        for (let i = lastActivityLen; i < feed.length; i++) {
          const evt = feed[i];
          if (evt.type === 'agent' && evt.content.startsWith('💬 ')) {
            const match = evt.content.match(/💬 (.+?) → (.+?): /);
            if (match) {
              this._showCommunicationBeam(match[1], match[2]);
            }
          }
        }
        lastActivityLen = feed.length;
      }
    });
    this.bridgeUnsubscribers.push(activityUnsub);

    // Subscribe to agent state changes
    this.storeUnsub = useStore.subscribe((state, prev) => {
      if (state.agents === prev.agents) return;

      const currentIds = new Set(state.agents.map((a) => a.id));

      // Spawn new agents, update status of existing ones
      for (const agent of state.agents) {
        const sprite = this.agentSprites.get(agent.id);
        if (!sprite) {
          this._spawnAgent(agent);
        } else {
          const prevAgent = prev.agents.find((a) => a.id === agent.id);
          if (prevAgent && prevAgent.status !== agent.status) {
            sprite.setStatus(agent.status);
          }
        }
      }

      // Remove agents that are gone
      for (const id of this.agentSprites.keys()) {
        if (!currentIds.has(id)) {
          this._removeAgent(id);
        }
      }
    });
  }

  // ── Click events (Phaser → React via GameBridge) ──────────────────────────

  private _setupClickBridge() {
    // Clicks are emitted directly in the pointer handlers below
  }

  // ── Workstations (invisible hit zones over background desks) ───────────────

  private _buildWorkstations() {
    for (const pos of WORKSTATION_POSITIONS) {
      // Debug: show hit zone outlines
      if (DEBUG_HIT_ZONES) {
        this.add
          .rectangle(pos.x, pos.y, pos.hitW, pos.hitH, 0xff0000, 0.15)
          .setStrokeStyle(1, 0xff0000, 0.5);
        this.add
          .text(pos.x, pos.y - pos.hitH / 2 + 4, pos.id, {
            fontSize: '7px',
            color: '#ff4444',
          })
          .setOrigin(0.5, 0);
      }

      // Invisible hit zone
      const hit = this.add
        .rectangle(pos.x, pos.y, pos.hitW, pos.hitH, 0xffffff, 0)
        .setInteractive({ cursor: 'pointer' });

      hit.on('pointerover', () => {
        hit.setFillStyle(0xffffff, 0.08); // subtle highlight on hover
      });
      hit.on('pointerout', () => {
        hit.setFillStyle(0xffffff, 0);
      });
      hit.on('pointerdown', () => {
        const agentId = this._agentAtWorkstation(pos.id);
        if (agentId) {
          GameBridge.emit(BRIDGE_EVENTS.AGENT_CLICKED, { agentId });
        } else {
          GameBridge.emit(BRIDGE_EVENTS.WORKSTATION_CLICKED, { id: pos.id });
        }
      });

      this.workstations.set(pos.id, { id: pos.id, x: pos.x, y: pos.y });
    }
  }

  // ── Interactive zones (whiteboard, filing cabinet) ─────────────────────────

  private _buildInteractiveZones() {
    const zones = [
      {
        ...INTERACTIVE_ZONES.WHITEBOARD,
        event: BRIDGE_EVENTS.WHITEBOARD_CLICKED,
        label: 'Whiteboard',
      },
      {
        ...INTERACTIVE_ZONES.FILING_CABINET,
        event: BRIDGE_EVENTS.FILING_CABINET_CLICKED,
        label: 'Filing Cabinet',
      },
    ];

    for (const zone of zones) {
      // Debug: show zone outlines
      if (DEBUG_HIT_ZONES) {
        this.add
          .rectangle(zone.x, zone.y, zone.w, zone.h, 0x00ff00, 0.15)
          .setStrokeStyle(1, 0x00ff00, 0.5);
        this.add
          .text(zone.x, zone.y, zone.label, {
            fontSize: '7px',
            color: '#44ff44',
          })
          .setOrigin(0.5);
      }

      const hit = this.add
        .rectangle(zone.x, zone.y, zone.w, zone.h, 0xffffff, 0)
        .setInteractive({ cursor: 'pointer' });

      hit.on('pointerover', () => {
        hit.setFillStyle(0xffffff, 0.06);
      });
      hit.on('pointerout', () => {
        hit.setFillStyle(0xffffff, 0);
      });
      hit.on('pointerdown', () => {
        GameBridge.emit(zone.event, {});
      });
    }
  }

  // ── Task count overlay (lightweight text on whiteboard area) ────────────────

  private _buildTaskCountOverlay() {
    const wb = INTERACTIVE_ZONES.WHITEBOARD;

    // Small task count text in the whiteboard area
    const countText = this.add
      .text(wb.x, wb.y + wb.h / 2 - 10, '', {
        fontSize: '8px',
        color: '#3a2a18',
        stroke: '#ffffff',
        strokeThickness: 2,
        align: 'center',
      })
      .setOrigin(0.5)
      .setDepth(1);

    // Pulsing active indicator
    const activeDot = this.add
      .circle(wb.x + wb.w / 2 - 10, wb.y - wb.h / 2 + 10, 4, 0x4caf50)
      .setStrokeStyle(1, 0x2e7d32)
      .setVisible(false)
      .setDepth(1);

    this.tweens.add({
      targets: activeDot,
      alpha: { from: 1, to: 0.3 },
      duration: 800,
      yoyo: true,
      repeat: -1,
      ease: 'Sine.easeInOut',
    });

    const updateCount = () => {
      const { tasks } = useStore.getState();
      const active = tasks.filter((t) => t.status === 'in_progress').length;
      if (tasks.length === 0) {
        countText.setText('');
        activeDot.setVisible(false);
      } else {
        const label = `${tasks.length} task${tasks.length !== 1 ? 's' : ''}`;
        countText.setText(active > 0 ? `${label} · ${active} active` : label);
        activeDot.setVisible(active > 0);
      }
    };
    updateCount();

    const unsub = useStore.subscribe((state, prev) => {
      if (state.tasks !== prev.tasks) updateCount();
    });
    this.bridgeUnsubscribers.push(unsub);
  }

  // ── PM sprite (always present at boss desk) ────────────────────────────────

  private _spawnPMSprite() {
    const PM_ID = 'pm-agent';
    if (this.agentSprites.has(PM_ID)) return;

    const sprite = new AgentSprite(
      this, PM_DESK_POSITION.x, PM_DESK_POSITION.y,
      PM_ID, 'PM', 'PM',
    );
    sprite.setStatus('idle');

    // PM portrait sprite is front-facing and looks oversized at normal scale — shrink it
    sprite.setScale(getPMScaleRatio());

    sprite.on('pointerdown', () => {
      GameBridge.emit(BRIDGE_EVENTS.AGENT_CLICKED, { agentId: PM_ID });
    });

    this.agentSprites.set(PM_ID, sprite);
  }

  // ── Agent management ───────────────────────────────────────────────────────

  private _spawnAgent(agent: Agent) {
    if (this.agentSprites.has(agent.id)) return;

    // PM agent goes to the boss desk; other agents go to workstations
    let spawnX: number;
    let spawnY: number;
    if (agent.role === 'PM') {
      spawnX = PM_DESK_POSITION.x;
      spawnY = PM_DESK_POSITION.y;
    } else {
      const ws = this.workstations.get(agent.workstation_id);
      if (!ws) return;
      spawnX = ws.x;
      spawnY = ws.y;
    }

    const sprite = new AgentSprite(
      this, spawnX, spawnY,
      agent.id, agent.name, agent.role,
    );
    sprite.setStatus(agent.status);

    // PM portrait sprite needs a smaller scale
    const targetScale = agent.role === 'PM' ? getPMScaleRatio() : 1;

    sprite.on('pointerdown', () => {
      GameBridge.emit(BRIDGE_EVENTS.AGENT_CLICKED, { agentId: agent.id });
    });

    this.agentSprites.set(agent.id, sprite);

    // Spawn pop animation
    sprite.setScale(0);
    this.tweens.add({
      targets: sprite,
      scaleX: targetScale,
      scaleY: targetScale,
      duration: 300,
      ease: 'Back.easeOut',
    });
  }

  private _removeAgent(agentId: string) {
    const sprite = this.agentSprites.get(agentId);
    if (!sprite) return;
    this.tweens.add({
      targets: sprite,
      scaleX: 0,
      scaleY: 0,
      duration: 200,
      onComplete: () => sprite.destroy(),
    });
    this.agentSprites.delete(agentId);
  }

  private _agentAtWorkstation(wsId: string): string | null {
    const agents = useStore.getState().agents;
    const agent = agents.find((a) => a.workstation_id === wsId);
    return agent?.id ?? null;
  }

  // ── Agent communication animation ──────────────────────────────────────────

  private _showCommunicationBeam(fromName: string, toName: string) {
    let fromSprite: AgentSprite | undefined;
    let toSprite: AgentSprite | undefined;
    const storeAgents = useStore.getState().agents;
    for (const agent of storeAgents) {
      if (agent.name === fromName) fromSprite = this.agentSprites.get(agent.id);
      if (agent.name === toName) toSprite = this.agentSprites.get(agent.id);
    }
    if (!fromSprite || !toSprite) return;

    const g = this.add.graphics();
    const x1 = fromSprite.x;
    const y1 = fromSprite.y - 10;
    const x2 = toSprite.x;
    const y2 = toSprite.y - 10;

    g.lineStyle(2, 0x8888ff, 0.7);
    const segments = 8;
    for (let i = 0; i < segments; i += 2) {
      const t1 = i / segments;
      const t2 = (i + 1) / segments;
      g.lineBetween(
        x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1,
        x1 + (x2 - x1) * t2, y1 + (y2 - y1) * t2,
      );
    }

    const bubble = this.add.text(x2, y2 - 24, '💬', { fontSize: '14px' }).setOrigin(0.5);

    this.tweens.add({
      targets: [g, bubble],
      alpha: 0,
      duration: 800,
      delay: 1200,
      onComplete: () => {
        g.destroy();
        bubble.destroy();
      },
    });
  }

  // ── Cleanup ────────────────────────────────────────────────────────────────

  private _cleanup() {
    this.storeUnsub?.();
    this.storeUnsub = undefined;
    this.bridgeUnsubscribers.forEach((fn) => fn());
    this.bridgeUnsubscribers = [];
    this.agentSprites.clear();
  }
}
