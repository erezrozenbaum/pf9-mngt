import React from 'react';
import './Skeleton.css';

interface Props {
  width?: string | number;
  height?: string | number;
  borderRadius?: string | number;
  className?: string;
  lines?: number;
  gap?: string;
}

export const Skeleton: React.FC<Props> = ({
  width = '100%',
  height = '1rem',
  borderRadius = '4px',
  className = '',
  lines,
  gap = '0.5rem',
}) => {
  if (lines && lines > 1) {
    return (
      <div className={`skeleton-group ${className}`} style={{ display: 'flex', flexDirection: 'column', gap }}>
        {Array.from({ length: lines }).map((_, i) => (
          <span
            key={i}
            className="skeleton"
            style={{
              width: i === lines - 1 && lines > 2 ? '60%' : '100%',
              height,
              borderRadius,
              display: 'block',
            }}
          />
        ))}
      </div>
    );
  }

  return (
    <span
      className={`skeleton ${className}`}
      style={{ width, height, borderRadius, display: 'block' }}
    />
  );
};

export const SkeletonCard: React.FC<{ rows?: number }> = ({ rows = 4 }) => (
  <div className="skeleton-card">
    <Skeleton height="1.1rem" width="50%" borderRadius="6px" />
    <div style={{ marginTop: '1rem' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-card-row">
          <Skeleton height="0.75rem" width={`${70 + Math.random() * 25}%`} />
        </div>
      ))}
    </div>
  </div>
);
