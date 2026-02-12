/**
 * ToolsList component - Sidebar showing available tools
 */

import React, { useState } from 'react';

export default function ToolsList({ tools }) {
  const [expandedTool, setExpandedTool] = useState(null);
  
  // Group tools by category
  const categories = {
    'Navigation': ['browser_launch', 'navigate', 'click', 'fill', 'browser_close'],
    'Extraction': ['get_content', 'extract_table', 'screenshot', 'execute_script'],
    'Search': ['search_web', 'wait_for_element', 'scroll_page'],
    'arXiv': ['arxiv_search', 'arxiv_get_paper', 'arxiv_download_pdf', 'arxiv_get_recent'],
    'IEEE': ['ieee_search', 'ieee_get_paper', 'ieee_download_pdf']
  };
  
  const toolsByCategory = {};
  Object.keys(categories).forEach(category => {
    toolsByCategory[category] = tools.filter(t => categories[category].includes(t.name));
  });
  
  return (
    <div className="h-full bg-gray-800 overflow-y-auto">
      <div className="p-4 border-b border-gray-700">
        <h2 className="text-lg font-semibold text-white">Available Tools</h2>
        <p className="text-xs text-gray-400 mt-1">{tools.length} tools loaded</p>
      </div>
      
      <div className="p-2">
        {Object.entries(toolsByCategory).map(([category, categoryTools]) => (
          <div key={category} className="mb-4">
            <h3 className="text-sm font-semibold text-gray-300 px-2 mb-2">
              {category}
            </h3>
            
            {categoryTools.map(tool => (
              <div key={tool.name} className="mb-1">
                <button
                  onClick={() => setExpandedTool(expandedTool === tool.name ? null : tool.name)}
                  className="w-full text-left px-3 py-2 rounded hover:bg-gray-700 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-white font-mono">{tool.name}</span>
                    <span className="text-xs text-gray-400">
                      {expandedTool === tool.name ? '▼' : '▶'}
                    </span>
                  </div>
                </button>
                
                {expandedTool === tool.name && (
                  <div className="px-3 py-2 bg-gray-900 rounded mx-2 mb-2">
                    <p className="text-xs text-gray-300 mb-2">
                      {tool.description}
                    </p>
                    
                    {tool.inputSchema?.properties && (
                      <div className="mt-2">
                        <p className="text-xs text-gray-400 mb-1">Parameters:</p>
                        {Object.entries(tool.inputSchema.properties).map(([param, schema]) => (
                          <div key={param} className="text-xs text-gray-400 ml-2 mb-1">
                            <span className="text-blue-400 font-mono">{param}</span>
                            {schema.type && (
                              <span className="text-gray-500"> ({schema.type})</span>
                            )}
                            {schema.description && (
                              <p className="text-gray-500 ml-4">{schema.description}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
