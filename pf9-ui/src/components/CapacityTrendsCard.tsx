import React from 'react';

interface CapacityPoint {
  day: string;
  new_vms: number;
  new_volumes: number;
  new_volume_gb: number;
}

interface CapacityTrendData {
  days: number;
  trendlines: CapacityPoint[];
  timestamp: string;
}

interface Props {
  data: CapacityTrendData;
}

export const CapacityTrendsCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="capacity-trends-card card">
      <h2>📦 Capacity Trends</h2>

      <div className="capacity-trends-table">
        <table>
          <thead>
            <tr>
              <th>Day</th>
              <th>New VMs</th>
              <th>New Volumes</th>
              <th>New Volume GB</th>
            </tr>
          </thead>
          <tbody>
            {data.trendlines.map((point) => (
              <tr key={point.day}>
                <td>{new Date(point.day).toLocaleDateString()}</td>
                <td>{point.new_vms}</td>
                <td>{point.new_volumes}</td>
                <td>{point.new_volume_gb.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
