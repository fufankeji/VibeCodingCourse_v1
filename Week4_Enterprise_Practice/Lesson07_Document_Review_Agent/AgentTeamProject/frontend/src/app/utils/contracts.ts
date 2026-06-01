import type { ContractItem } from '../api/contracts';

export function contractState(contract: ContractItem): string {
  return contract.session_state || contract.contract_status || 'processing';
}

export function contractRoute(contract: ContractItem): string | null {
  const state = contractState(contract);
  const sid = contract.session_id;
  if (!sid) return null;
  if (state === 'aborted') return null;
  if (state === 'parsing') return `/contracts/${sid}/parsing`;
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
