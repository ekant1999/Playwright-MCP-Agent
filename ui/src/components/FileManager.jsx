/**
 * FileManager component - View and download files
 */

import React, { useState, useEffect } from 'react';
import { getFiles, getFileUrl } from '../services/mcp.js';

export default function FileManager() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  
  const loadFiles = async () => {
    setLoading(true);
    try {
      const fileList = await getFiles();
      setFiles(fileList);
    } catch (error) {
      console.error('Failed to load files:', error);
    } finally {
      setLoading(false);
    }
  };
  
  useEffect(() => {
    loadFiles();
    
    // Poll for new files every 5 seconds
    const interval = setInterval(loadFiles, 5000);
    return () => clearInterval(interval);
  }, []);
  
  const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };
  
  return (
    <div className="h-1/2 bg-gray-800 overflow-y-auto">
      <div className="p-3 border-b border-gray-700 sticky top-0 bg-gray-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Downloaded Files</h3>
        <button
          onClick={loadFiles}
          disabled={loading}
          className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>
      
      <div className="p-2 space-y-1">
        {files.length === 0 && !loading && (
          <p className="text-xs text-gray-400 text-center py-4">
            No files yet
          </p>
        )}
        
        {files.map((file, idx) => (
          <a
            key={idx}
            href={getFileUrl(file.filename)}
            download
            className="block px-2 py-2 bg-gray-900 rounded hover:bg-gray-700 transition-colors"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="text-xs text-white truncate font-mono">
                  {file.filename}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">
                  {formatFileSize(file.size)}
                </div>
              </div>
              <span className="text-xs text-gray-500 whitespace-nowrap">
                {new Date(file.modified).toLocaleTimeString()}
              </span>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
