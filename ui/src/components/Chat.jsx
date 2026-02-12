/**
 * Chat component - Message list and input
 */

import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';

export default function Chat({ messages, onSendMessage, isProcessing }) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  
  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);
  
  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px';
    }
  }, [input]);
  
  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isProcessing) {
      onSendMessage(input.trim());
      setInput('');
    }
  };
  
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };
  
  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 mt-8">
            <p className="text-lg mb-4">Welcome to Playwright MCP Agent</p>
            <p className="text-sm">Ask me to browse the web, search for papers, or fetch content.</p>
          </div>
        )}
        
        {messages.map((msg, idx) => (
          <Message key={idx} message={msg} />
        ))}
        
        <div ref={messagesEndRef} />
      </div>
      
      {/* Input */}
      <div className="border-t border-gray-700 p-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask me anything..."
            disabled={isProcessing}
            className="flex-1 bg-gray-800 text-white rounded-lg px-4 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 min-h-[44px] max-h-[200px]"
            rows={1}
          />
          <button
            type="submit"
            disabled={!input.trim() || isProcessing}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isProcessing ? 'Processing...' : 'Send'}
          </button>
        </form>
      </div>
    </div>
  );
}

function Message({ message }) {
  const [expanded, setExpanded] = useState(false);
  
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="bg-blue-600 text-white rounded-lg px-4 py-2 max-w-[80%]">
          {message.content}
        </div>
      </div>
    );
  }
  
  if (message.role === 'assistant') {
    return (
      <div className="flex justify-start">
        <div className="bg-gray-800 text-white rounded-lg px-4 py-3 max-w-[80%]">
          <ReactMarkdown
            className="prose prose-invert max-w-none"
            components={{
              code: ({ node, inline, ...props }) => (
                inline
                  ? <code className="bg-gray-700 px-1 py-0.5 rounded text-sm" {...props} />
                  : <code className="block bg-gray-700 p-2 rounded text-sm overflow-x-auto" {...props} />
              ),
              pre: ({ node, ...props }) => (
                <pre className="bg-gray-700 p-2 rounded overflow-x-auto" {...props} />
              )
            }}
          >
            {message.content}
          </ReactMarkdown>
        </div>
      </div>
    );
  }
  
  if (message.role === 'tool') {
    return (
      <div className="flex justify-start">
        <div className="bg-gray-700 text-gray-300 rounded-lg px-4 py-3 max-w-[80%]">
          <div 
            className="flex items-center justify-between cursor-pointer mb-2"
            onClick={() => setExpanded(!expanded)}
          >
            <div className="flex items-center gap-2">
              <span className="text-green-400">🔧</span>
              <span className="font-semibold text-sm">{message.toolName}</span>
              <span className="text-xs text-gray-400">
                {message.status === 'success' ? '✓' : '✗'}
              </span>
            </div>
            <span className="text-xs text-gray-400">
              {expanded ? '▼' : '▶'}
            </span>
          </div>
          
          {expanded && (
            <div className="mt-2 text-xs font-mono bg-gray-800 p-2 rounded overflow-x-auto">
              <pre className="whitespace-pre-wrap">{message.result}</pre>
            </div>
          )}
        </div>
      </div>
    );
  }
  
  return null;
}
