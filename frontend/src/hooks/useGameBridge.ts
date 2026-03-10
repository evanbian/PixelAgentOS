import { useEffect } from 'react';
import { GameBridge, BRIDGE_EVENTS } from '../game/GameBridge';
import { useStore } from '../store/useStore';

interface GameBridgeOptions {
  onWhiteboardClick?: () => void;
  onFilingCabinetClick?: () => void;
}

/**
 * Hook: wires Phaser click events → React UI actions.
 * Agent syncing to Phaser is handled inside OfficeScene via Zustand subscribe,
 * so we only need to handle the reverse direction here.
 */
export function useGameBridge(options: GameBridgeOptions = {}) {
  const { openCreateAgentModal, setSelectedAgent, toggleTaskDashboard } = useStore();

  useEffect(() => {
    const unsubWS = GameBridge.on(BRIDGE_EVENTS.WORKSTATION_CLICKED, (data) => {
      const { id } = data as { id: string };
      openCreateAgentModal(id);
    });

    const unsubAgent = GameBridge.on(BRIDGE_EVENTS.AGENT_CLICKED, (data) => {
      const { agentId } = data as { agentId: string };
      setSelectedAgent(agentId);
    });

    const unsubWB = GameBridge.on(BRIDGE_EVENTS.WHITEBOARD_CLICKED, () => {
      if (options.onWhiteboardClick) {
        options.onWhiteboardClick();
      } else {
        toggleTaskDashboard();
      }
    });

    const unsubFC = GameBridge.on(BRIDGE_EVENTS.FILING_CABINET_CLICKED, () => {
      options.onFilingCabinetClick?.();
    });

    return () => {
      unsubWS();
      unsubAgent();
      unsubWB();
      unsubFC();
    };
  }, [openCreateAgentModal, setSelectedAgent, toggleTaskDashboard, options.onWhiteboardClick, options.onFilingCabinetClick]);
}
