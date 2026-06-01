import type { ContractItem } from '../api/contracts';

export function contractState(contract: ContractItem): string {
  return contract.session_state || 'processing';
}

export function contractRoute(contract: ContractItem): string | null {
  const sid = contract.session_id;
  if (!sid) return null;
  if (contract.entry_route_type) return routeForEntryType(sid, contract.entry_route_type);
  const state = contractState(contract);
  if (state === 'aborted') return `/contracts/${sid}/parsing`;
  if (state === 'parsing') return `/contracts/${sid}/parsing`;
  if (state === 'parsed') return `/contracts/${sid}/parsing`;
  if (state === 'scanning' || state === 'hitl_field_verify') return `/contracts/${sid}/fields`;
  if (state === 'hitl_medium_confirm') return `/contracts/${sid}/batch`;
  if (state === 'report_ready' || state === 'completed') return `/contracts/${sid}/report`;
  if (state === 'hitl_pending' || state === 'hitl_high_risk') return `/contracts/${sid}/review`;
  if (state === 'processing') return null;
  return `/contracts/${sid}/review`;
}

export function isContractNavigable(contract: ContractItem): boolean {
  return contractRoute(contract) !== null;
}

function routeForEntryType(sessionId: string, entryType: ContractItem['entry_route_type']): string | null {
  if (entryType === 'parsing' || entryType === 'aborted') return `/contracts/${sessionId}/parsing`;
  if (entryType === 'fields') return `/contracts/${sessionId}/fields`;
  if (entryType === 'batch') return `/contracts/${sessionId}/batch`;
  if (entryType === 'report') return `/contracts/${sessionId}/report`;
  if (entryType === 'review') return `/contracts/${sessionId}/review`;
  return null;
}
