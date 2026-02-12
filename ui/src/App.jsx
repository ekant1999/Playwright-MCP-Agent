/**
 * Main App component
 */

import React, { useState, useEffect } from 'react';
import Chat from './components/Chat.jsx';
import ToolsList from './components/ToolsList.jsx';
import ActivityLog from './components/ActivityLog.jsx';
import FileManager from './components/FileManager.jsx';
import { checkOllamaStatus, streamChat } from './services/ollama.js';
import { checkHealth, getTools, callTool } from './services/mcp.js';
import { EXAMPLE_PROMPTS } from './config.js';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [tools, setTools] = useState([]);
  const [activities, setActivities] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [status, setStatus] = useState({
    ollama: false,
    bridge: false,
    loading: true
  });
  
  // Initialize - check Ollama and bridge server
  useEffect(() => {
    async function initialize() {
      try {
        // Check Ollama
        const ollamaStatus = await checkOllamaStatus();
        
        // Check bridge
        let bridgeStatus = false;
        let toolsList = [];
        try {
          await checkHealth();
          toolsList = await getTools();
          bridgeStatus = true;
        } catch (e) {
          console.error('Bridge not ready:', e);
        }
        
        setStatus({
          ollama: ollamaStatus.running && ollamaStatus.hasModel,
          bridge: bridgeStatus,
          loading: false
        });
        
        setTools(toolsList);
        
        // Show welcome message
        if (ollamaStatus.running && ollamaStatus.hasModel && bridgeStatus) {
          setMessages([{
            role: 'assistant',
            content: `Ready to help! I have access to ${toolsList.length} tools for browsing the web and searching research papers.\n\n**Try asking:**\n${EXAMPLE_PROMPTS.map(p => `- ${p}`).join('\n')}`
          }]);
        }
      } catch (error) {
        console.error('Initialization error:', error);
        setStatus({ ollama: false, bridge: false, loading: false });
      }
    }
    
    initialize();
  }, []);
  
  // Handle sending a message
  const handleSendMessage = async (content) => {
    // Add user message
    const userMessage = { role: 'user', content };
    setMessages(prev => [...prev, userMessage]);
    setIsProcessing(true);
    
    // Start assistant message
    let assistantContent = '';
    const assistantMessageIndex = messages.length + 1;
    
    try {
      // Stream chat with tool calling
      await streamChat(
        [...messages, userMessage],
        tools,
        (chunk) => {
          if (chunk.type === 'content') {
            assistantContent += chunk.content;
            
            // Update assistant message
            setMessages(prev => {
              const newMessages = [...prev];
              const lastMsg = newMessages[newMessages.length - 1];
              
              if (lastMsg && lastMsg.role === 'assistant') {
                lastMsg.content = assistantContent;
              } else {
                newMessages.push({
                  role: 'assistant',
                  content: assistantContent
                });
              }
              
              return newMessages;
            });
          } else if (chunk.type === 'tool_call_start') {
            // Add activity
            const activity = {
              toolName: chunk.toolCall.function.name,
              status: 'pending',
              timestamp: new Date().toISOString()
            };
            setActivities(prev => [...prev, activity]);
          } else if (chunk.type === 'tool_call_end') {
            // Update activity
            setActivities(prev => {
              const newActivities = [...prev];
              const lastActivity = newActivities[newActivities.length - 1];
              if (lastActivity && lastActivity.toolName === chunk.toolCall.function.name) {
                lastActivity.status = 'success';
              }
              return newActivities;
            });
            
            // Add tool message
            setMessages(prev => [...prev, {
              role: 'tool',
              toolName: chunk.toolCall.function.name,
              result: chunk.result,
              status: 'success'
            }]);
          } else if (chunk.type === 'tool_call_error') {
            // Update activity
            setActivities(prev => {
              const newActivities = [...prev];
              const lastActivity = newActivities[newActivities.length - 1];
              if (lastActivity && lastActivity.toolName === chunk.toolCall.function.name) {
                lastActivity.status = 'error';
                lastActivity.error = chunk.error;
              }
              return newActivities;
            });
            
            // Add tool message
            setMessages(prev => [...prev, {
              role: 'tool',
              toolName: chunk.toolCall.function.name,
              result: chunk.error,
              status: 'error'
            }]);
          } else if (chunk.type === 'error') {
            assistantContent += `\n\n**Error:** ${chunk.error}`;
            setMessages(prev => {
              const newMessages = [...prev];
              newMessages.push({
                role: 'assistant',
                content: assistantContent
              });
              return newMessages;
            });
          }
        },
        async (toolName, toolArgs) => {
          // Execute tool via bridge
          return await callTool(toolName, toolArgs);
        }
      );
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `**Error:** ${error.message}\n\nPlease check that Ollama and the bridge server are running.`
      }]);
    } finally {
      setIsProcessing(false);
    }
  };
  
  if (status.loading) {
    return (
      <div className="h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-center">
          <div className="text-4xl mb-4">🔄</div>
          <div>Loading...</div>
        </div>
      </div>
    );
  }
  
  if (!status.ollama || !status.bridge) {
    return (
      <div className="h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-center max-w-md">
          <div className="text-4xl mb-4">⚠️</div>
          <h1 className="text-2xl font-bold mb-4">Setup Required</h1>
          
          <div className="text-left space-y-2 mb-6">
            <div className="flex items-center gap-2">
              <span className={status.ollama ? 'text-green-400' : 'text-red-400'}>
                {status.ollama ? '✓' : '✗'}
              </span>
              <span>Ollama (qwen2.5 model)</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={status.bridge ? 'text-green-400' : 'text-red-400'}>
                {status.bridge ? '✓' : '✗'}
              </span>
              <span>Bridge Server</span>
            </div>
          </div>
          
          <div className="text-sm text-gray-400">
            {!status.ollama && (
              <p className="mb-2">
                Install Ollama and run: <code className="bg-gray-800 px-2 py-1">ollama pull qwen2.5</code>
              </p>
            )}
            {!status.bridge && (
              <p>
                Start the bridge server: <code className="bg-gray-800 px-2 py-1">cd bridge_server && node server.js</code>
              </p>
            )}
          </div>
          
          <button
            onClick={() => window.location.reload()}
            className="mt-6 bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }
  
  return (
    <div className="h-screen bg-gray-900 flex">
      {/* Left sidebar - Tools */}
      <div className="w-64 border-r border-gray-700 flex-shrink-0">
        <ToolsList tools={tools} />
      </div>
      
      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <Chat
          messages={messages}
          onSendMessage={handleSendMessage}
          isProcessing={isProcessing}
        />
      </div>
      
      {/* Right sidebar - Activity & Files */}
      <div className="w-80 border-l border-gray-700 flex-shrink-0 flex flex-col">
        <ActivityLog activities={activities} />
        <FileManager />
      </div>
    </div>
  );
}
