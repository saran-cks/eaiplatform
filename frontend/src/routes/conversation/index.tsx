import { ConversationView } from "@/features/conversation/ConversationView";

/**
 * Unified chat + agent surface (mode toggle by the composer). F2 wires chat
 * mode; F3 adds agent mode + the ephemeral ActionStream + Monaco artifacts.
 */
export function ConversationPage() {
  return <ConversationView />;
}
