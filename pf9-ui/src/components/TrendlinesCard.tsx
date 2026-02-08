import React from 'react';

interface TrendPoint {
  day: string;
  new_vms: number;
  snapshots_created: number;
  deleted_resources: number;
}

interface TrendlineData {
  days: number;
  trendlines: TrendPoint[];
  timestamp: string;
}

interface Props {
  data: TrendlineData;
}

export const TrendlinesCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="trendlines-card card">
      <h2>📊 Activity Trendlines</h2>

      <div className="trendlines-table">
        <table>
          <thead>
            <tr>
              <th>Day</th>
              <th>New VMs</th>
              <th>Snapshots</th>
              <th>Deletions</th>
            </tr>
          </thead>
          <tbody>
            {data.trendlines.map((point) => (
              <tr key={point.day}>
                <td>{new Date(point.day).toLocaleDateString()}</td>
                <td>{point.new_vms}</td>
                <td>{point.snapshots_created}</td>
                <td>{point.deleted_resources}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
