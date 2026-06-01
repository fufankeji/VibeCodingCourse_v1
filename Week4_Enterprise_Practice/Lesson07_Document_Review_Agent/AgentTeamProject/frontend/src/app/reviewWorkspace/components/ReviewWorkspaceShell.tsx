import type { ReactNode } from 'react';
import { GlobalNav } from '../../components/GlobalNav';
import { WorkflowStatusBar } from '../../components/WorkflowStatusBar';
import type { SessionState } from '../../types';

interface ReviewWorkspaceShellProps {
  sessionState: SessionState;
  scanningStarted?: boolean;
  header: ReactNode;
  navigator: ReactNode;
  viewer: ReactNode;
  stagePanel: ReactNode;
}

export function ReviewWorkspaceShell({
  sessionState,
  scanningStarted,
  header,
  navigator,
  viewer,
  stagePanel,
}: ReviewWorkspaceShellProps) {
  return (
    <div className="min-h-screen bg-slate-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState={sessionState} scanningStarted={scanningStarted} />
      <main className="pt-[118px]">
        <div className="mx-auto max-w-[1760px] px-4 py-6 sm:px-6 lg:px-8">
          {header}
          <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_420px]">
            {navigator}
            {viewer}
            {stagePanel}
          </div>
        </div>
      </main>
    </div>
  );
}
