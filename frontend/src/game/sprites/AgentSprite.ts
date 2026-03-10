import Phaser from 'phaser';
import type { AgentStatus } from '../../types';
import {
  SPRITE_CONFIG, STATUS_FRAME_INDEX,
  STATUS_EMOTE_KEYS, IDLE_EMOTE_KEYS, IDLE_EMOTE_INTERVAL, IDLE_EMOTE_DURATION,
  getTextureKeyForRole, DEFAULT_SPRITE_KEY,
} from '../config';

// Lazy-evaluated to avoid circular-dependency TDZ issues
function S(): number { return SPRITE_CONFIG.DISPLAY_SCALE; }
function HALF_H(): number { return (SPRITE_CONFIG.FRAME_HEIGHT * S()) / 2; }

// Bubble background colours per status
const BUBBLE_COLORS: Record<string, number> = {
  idle:          0x3a4570,
  working:       0x2e7d32,
  thinking:      0xf57f17,
  communicating: 0x1565c0,
};
const BUBBLE_R = 12;            // bubble circle radius (game px)
const ICON_SCALE = 18 / 72;    // twemoji is 72×72, display at 18px

export class AgentSprite extends Phaser.GameObjects.Container {
  private character!: Phaser.GameObjects.Sprite;
  private nameText!: Phaser.GameObjects.Text;

  // Emote bubble (background circle + twemoji image)
  private emoteBubble?: Phaser.GameObjects.Arc;
  private emoteIcon?: Phaser.GameObjects.Image;
  private emoteTween?: Phaser.Tweens.Tween;
  private idleEmoteTimer?: Phaser.Time.TimerEvent;
  private idleEmoteHideTimer?: Phaser.Time.TimerEvent;

  // Text speech bubble (for agent messages)
  private bubbleText?: Phaser.GameObjects.Text;
  private bubbleBg?: Phaser.GameObjects.Rectangle;
  private bubbleTimer?: Phaser.Time.TimerEvent;
  private statusTween?: Phaser.Tweens.Tween;

  agentId: string;
  agentName: string;
  agentRole: string;
  currentStatus: AgentStatus = 'idle';

  constructor(
    scene: Phaser.Scene,
    x: number,
    y: number,
    agentId: string,
    name: string,
    role: string,
  ) {
    super(scene, x, y);
    this.agentId = agentId;
    this.agentName = name;
    this.agentRole = role;

    this._buildSprite(role, name);
    this._setupInteraction();

    scene.add.existing(this);
  }

  // ── Build pixel character sprite ───────────────────────────────────────────

  private _buildSprite(role: string, name: string) {
    const textureKey = getTextureKeyForRole(role);
    const key = this.scene.textures.exists(textureKey) ? textureKey : DEFAULT_SPRITE_KEY;

    this.character = this.scene.add.sprite(0, 0, key, STATUS_FRAME_INDEX.idle);
    this.character.setScale(S());
    this.add(this.character);

    // Start idle tween
    this._applyStatusTween('idle');

    // Name label below character
    this.nameText = this.scene.add.text(0, HALF_H() + 2, name, {
      fontSize: '8px',
      color: '#ffffff',
      stroke: '#000000',
      strokeThickness: 2,
      align: 'center',
    }).setOrigin(0.5, 0);
    this.add(this.nameText);

    // Start idle emote loop (default state)
    this._startIdleEmoteLoop();
  }

  // ── Interaction hit zone ───────────────────────────────────────────────────

  private _setupInteraction() {
    this.setSize(SPRITE_CONFIG.FRAME_WIDTH * S(), SPRITE_CONFIG.FRAME_HEIGHT * S() + 16);
    this.setInteractive({ cursor: 'pointer' });
    this.on('pointerover', () => {
      this.character.setAlpha(0.85);
    });
    this.on('pointerout', () => {
      this.character.setAlpha(1);
    });
  }

  // ── Status updates ─────────────────────────────────────────────────────────

  setStatus(status: AgentStatus) {
    if (this.currentStatus === status) return;
    this.currentStatus = status;

    // Switch character frame
    const frameIndex = STATUS_FRAME_INDEX[status] ?? 0;
    this.character.setFrame(frameIndex);

    // Reset character transform before new tween
    this._resetCharacterTransform();
    this._applyStatusTween(status);

    // Update emote display
    this._updateEmote(status);
  }

  // ── Emote bubble (Twemoji image + coloured circle background) ─────────────

  private _updateEmote(status: AgentStatus) {
    this._hideEmote();
    this._stopIdleEmoteLoop();

    if (status === 'idle') {
      this._startIdleEmoteLoop();
      return;
    }

    // Show persistent emote for active statuses
    const emoteKey = STATUS_EMOTE_KEYS[status];
    if (emoteKey) {
      this._showEmoteBubble(emoteKey, BUBBLE_COLORS[status] ?? 0x3a4570);
    }
  }

  private _showEmoteBubble(textureKey: string, color: number) {
    this._hideEmote();

    if (!this.scene.textures.exists(textureKey)) return;

    const bubbleY = -HALF_H() - BUBBLE_R - 2;

    // White circle background with coloured border for high contrast
    this.emoteBubble = this.scene.add.arc(0, bubbleY, BUBBLE_R, 0, 360, false, 0xffffff, 0.95);
    this.emoteBubble.setStrokeStyle(2, color, 1);
    this.add(this.emoteBubble);

    // Twemoji icon (72×72 source → 12px display via scale)
    this.emoteIcon = this.scene.add.image(0, bubbleY, textureKey);
    this.emoteIcon.setScale(ICON_SCALE);
    this.add(this.emoteIcon);

    // Gentle floating bob
    this.emoteTween = this.scene.tweens.add({
      targets: [this.emoteBubble, this.emoteIcon],
      y: { from: bubbleY, to: bubbleY - 2 },
      duration: 1000,
      yoyo: true,
      repeat: -1,
      ease: 'Sine.easeInOut',
    });
  }

  private _hideEmote() {
    this.emoteTween?.stop();
    this.emoteTween = undefined;
    this.emoteBubble?.destroy();
    this.emoteBubble = undefined;
    this.emoteIcon?.destroy();
    this.emoteIcon = undefined;
  }

  private _startIdleEmoteLoop() {
    this.idleEmoteTimer = this.scene.time.addEvent({
      delay: IDLE_EMOTE_INTERVAL,
      loop: true,
      callback: () => {
        if (this.currentStatus !== 'idle') return;
        const key = IDLE_EMOTE_KEYS[Math.floor(Math.random() * IDLE_EMOTE_KEYS.length)];
        this._showEmoteBubble(key, BUBBLE_COLORS.idle);

        // Pop-in animation (tween to each object's own target scale)
        if (this.emoteBubble && this.emoteIcon) {
          this.emoteBubble.setScale(0);
          this.scene.tweens.add({
            targets: this.emoteBubble,
            scaleX: 1, scaleY: 1,
            duration: 250,
            ease: 'Back.easeOut',
          });
          this.emoteIcon.setScale(0);
          this.scene.tweens.add({
            targets: this.emoteIcon,
            scaleX: ICON_SCALE, scaleY: ICON_SCALE,
            duration: 250,
            ease: 'Back.easeOut',
          });
        }

        // Auto-hide after duration
        this.idleEmoteHideTimer = this.scene.time.delayedCall(IDLE_EMOTE_DURATION, () => {
          if (this.emoteBubble && this.emoteIcon) {
            this.scene.tweens.add({
              targets: [this.emoteBubble, this.emoteIcon],
              alpha: 0, scaleX: 0.3, scaleY: 0.3,
              duration: 300,
              ease: 'Sine.easeIn',
              onComplete: () => this._hideEmote(),
            });
          }
        });
      },
    });
  }

  private _stopIdleEmoteLoop() {
    this.idleEmoteTimer?.remove();
    this.idleEmoteTimer = undefined;
    this.idleEmoteHideTimer?.remove();
    this.idleEmoteHideTimer = undefined;
  }

  // ── Tween animations per status ────────────────────────────────────────────

  private _resetCharacterTransform() {
    if (this.statusTween) {
      this.statusTween.stop();
      this.statusTween = undefined;
    }
    this.character.setPosition(0, 0);
    this.character.setAngle(0);
    this.character.setScale(S());
  }

  private _applyStatusTween(status: string) {
    switch (status) {
      case 'idle':
        this.statusTween = this.scene.tweens.add({
          targets: this.character,
          y: { from: 0, to: -2 },
          duration: 1500,
          yoyo: true,
          repeat: -1,
          ease: 'Sine.easeInOut',
        });
        break;

      case 'working':
        this.statusTween = this.scene.tweens.add({
          targets: this.character,
          x: { from: -1, to: 1 },
          duration: 100,
          yoyo: true,
          repeat: -1,
          ease: 'Linear',
        });
        break;

      case 'thinking':
        this.statusTween = this.scene.tweens.add({
          targets: this.character,
          angle: { from: -3, to: 3 },
          duration: 800,
          yoyo: true,
          repeat: -1,
          ease: 'Sine.easeInOut',
        });
        break;

      case 'communicating':
        this.statusTween = this.scene.tweens.add({
          targets: this.character,
          scaleX: { from: S(), to: S() * 1.06 },
          scaleY: { from: S(), to: S() * 1.06 },
          duration: 400,
          yoyo: true,
          repeat: -1,
          ease: 'Sine.easeInOut',
        });
        break;
    }
  }

  // ── Speech bubble (for agent message content) ─────────────────────────────

  showBubble(text: string, duration: number = 4000) {
    this.hideBubble();

    const maxWidth = 110;
    const padding = 6;
    const hasEmote = !!(this.emoteBubble);
    const baseY = hasEmote ? -HALF_H() - BUBBLE_R * 2 - 10 : -HALF_H() - 14;

    this.bubbleBg = this.scene.add.rectangle(
      0, baseY, maxWidth, 18, 0x000000, 0.8,
    ).setOrigin(0.5, 1);

    this.bubbleText = this.scene.add.text(
      0, baseY + 8, text, {
      fontSize: '7px',
      color: '#ffffff',
      wordWrap: { width: maxWidth - padding * 2 },
      align: 'center',
    }).setOrigin(0.5, 1);

    const bounds = this.bubbleText.getBounds();
    this.bubbleBg.setSize(maxWidth, Math.max(18, bounds.height + padding * 2));
    this.bubbleBg.setY(-bounds.height - HALF_H() + (hasEmote ? -BUBBLE_R * 2 + 2 : 2));
    this.bubbleText.setY(-bounds.height - padding - HALF_H() + (hasEmote ? -BUBBLE_R * 2 + 8 : 8));

    this.add([this.bubbleBg, this.bubbleText]);

    if (duration < 999999) {
      this.bubbleTimer = this.scene.time.delayedCall(duration, () => {
        this.hideBubble();
      });
    }
  }

  hideBubble() {
    this.bubbleTimer?.remove();
    this.bubbleBg?.destroy();
    this.bubbleText?.destroy();
    this.bubbleBg = undefined;
    this.bubbleText = undefined;
  }

  setMessageBubble(content: string) {
    const short = content.length > 50 ? content.slice(0, 50) + '...' : content;
    this.showBubble(short, 5000);
  }

  destroy(fromScene?: boolean) {
    this.statusTween?.stop();
    this.emoteTween?.stop();
    this._stopIdleEmoteLoop();
    this.bubbleTimer?.remove();
    super.destroy(fromScene);
  }
}
