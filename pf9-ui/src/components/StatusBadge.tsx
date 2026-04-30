import React from 'react';
import './StatusBadge.css';

type StatusVariant =
  | 'active'
  | 'inactive'
  | 'running'
  | 'stopped'
  | 'error'
  | 'warning'
  | 'critical'
  | 'healthy'
  | 'degraded'
  | 'unknown'
  | 'enabled'
  | 'disabled';

interface Props {
  status: StatusVariant | string;
  label?: string;
  dot?: boolean;
  size?: 'sm' | 'md';
}

const STATUS_MAP: Record<string, { variant: string; defaultLabel: string }> = {
  active:   { variant: 'success', defaultLabel: 'Active' },
  running:  { variant: 'success', defaultLabel: 'Running' },
  healthy:  { variant: 'success', defaultLabel: 'Healthy' },
  enabled:  { variant: 'success', defaultLabel: 'Enabled' },
  inactive: { variant: 'neutral', defaultLabel: 'Inactive' },
  stopped:  { variant: 'neutral', defaultLabel: 'Stopped' },
  disabled: { variant: 'neutral', defaultLabel: 'Disabled' },
  unknown:  { variant: 'neutral', defaultLabel: 'Unknown' },
  warning:  { variant: 'warning', defaultLabel: 'Warning' },
  degraded: { variant: 'warning', defaultLabel: 'Degraded' },
  error:    { variant: 'error',   defaultLabel: 'Error' },
  critical: { variant: 'error',   defaultLabel: 'Critical' },
};

export const StatusBadge: React.FC<Props> = ({
  status,
  label,
  dot = true,
  size = 'md',
}) => {
  const key = status.toLowerCase();
  const { variant, defaultLabel } = STATUS_MAP[key] ?? { variant: 'neutral', defaultLabel: status };
  const displayLabel = label ?? defaultLabel;

  return (
    <span className={`status-badge status-badge--${variant} status-badge--${size}`}>
      {dot && <span className="status-badge__dot" aria-hidden="true" />}
      {displayLabel}
    </span>
  );
};
