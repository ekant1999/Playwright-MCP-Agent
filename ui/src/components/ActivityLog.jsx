/**
 * ActivityLog component - Real-time tool execution log
 */

import React from 'react';

export default function ActivityLog({ activities }) {
  return (
    <div className="h-1/2 bg-gray-800 border-b border-gray-700 overflow-y-auto">
      <div className="p-3 border-b border-gray-700 sticky top-0 bg-gray-800">
        <h3 className="text-sm font-semibold text-white">Activity Log</h3>
      </div>
      
      <div className="p-2 space-y-1">
        {activities.length === 0 && (
          <p className="text-xs text-gray-400 text-center py-4">
            No activity yet
          </p>
        )}
        
        {activities.map((activity, idx) => (
          <ActivityItem key={idx} activity={activity} />
        ))}
      </div>
    </div>
  );
}

function ActivityItem({ activity }) {
  const getStatusColor = (status) => {
    switch (status) {
      case 'pending': return 'text-yellow-400';
      case 'success': return 'text-green-400';
      case 'error': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };
  
  const getStatusIcon = (status) => {
    switch (status) {
      case 'pending': return '⏳';
      case 'success': return '✓';
      case 'error': return '✗';
      default: return '•';
    }
  };
  
  return (
    <div className="px-2 py-1.5 bg-gray-900 rounded text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 flex-1 min-w-0">
          <span className={getStatusColor(activity.status)}>
            {getStatusIcon(activity.status)}
          </span>
          <div className="flex-1 min-w-0">
            <div className="font-mono text-white truncate">
              {activity.toolName}
            </div>
            {activity.error && (
              <div className="text-red-400 text-xs mt-1 break-words">
                {activity.error}
              </div>
            )}
          </div>
        </div>
        <span className="text-gray-500 text-xs whitespace-nowrap">
          {new Date(activity.timestamp).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}
