/**
 * Ollama service - Stream chat with tool calling support
 */

import axios from 'axios';
import { OLLAMA_URL, MODEL, SYSTEM_PROMPT } from '../config.js';

const api = axios.create({
  baseURL: OLLAMA_URL,
  timeout: 0 // No timeout for streaming
});

/**
 * Check if Ollama is running
 */
export async function checkOllamaStatus() {
  try {
    const response = await axios.get(`${OLLAMA_URL}/api/tags`, { timeout: 5000 });
    const models = response.data.models || [];
    const hasModel = models.some(m => m.name.includes(MODEL));
    
    return {
      running: true,
      hasModel,
      models: models.map(m => m.name)
    };
  } catch (error) {
    return {
      running: false,
      hasModel: false,
      models: []
    };
  }
}

/**
 * Convert MCP tools to Ollama function format
 */
function convertToolsToFunctions(tools) {
  return tools.map(tool => ({
    type: 'function',
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.inputSchema || { type: 'object', properties: {} }
    }
  }));
}

/**
 * Stream chat with tool calling
 * @param {Array} messages - Conversation messages (without system prompt)
 * @param {Array} tools - Available MCP tools
 * @param {Function} onChunk - Callback for each chunk (content or tool_call)
 * @param {Function} onToolCall - Async callback to execute tool calls
 */
export async function streamChat(messages, tools, onChunk, onToolCall) {
  const MAX_ITERATIONS = 15;
  let iteration = 0;
  
  // Build conversation with system prompt
  let conversation = [
    { role: 'system', content: SYSTEM_PROMPT },
    ...messages
  ];
  
  // Convert tools to Ollama format
  const ollamaTools = convertToolsToFunctions(tools);
  
  while (iteration < MAX_ITERATIONS) {
    iteration++;
    
    try {
      const response = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          model: MODEL,
          messages: conversation,
          tools: ollamaTools,
          stream: true
        })
      });
      
      if (!response.ok) {
        throw new Error(`Ollama API error: ${response.statusText}`);
      }
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      let assistantMessage = { role: 'assistant', content: '' };
      let toolCalls = [];
      let buffer = '';
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer
        
        for (const line of lines) {
          if (!line.trim()) continue;
          
          try {
            const data = JSON.parse(line);
            
            // Handle content
            if (data.message?.content) {
              assistantMessage.content += data.message.content;
              onChunk({
                type: 'content',
                content: data.message.content
              });
            }
            
            // Handle tool calls
            if (data.message?.tool_calls && data.message.tool_calls.length > 0) {
              toolCalls = data.message.tool_calls;
            }
            
            // Check if done
            if (data.done) {
              // If we have tool calls, execute them
              if (toolCalls.length > 0) {
                // Add assistant message with tool calls
                assistantMessage.tool_calls = toolCalls;
                conversation.push(assistantMessage);
                
                // Execute each tool call
                for (const toolCall of toolCalls) {
                  onChunk({
                    type: 'tool_call_start',
                    toolCall
                  });
                  
                  try {
                    const result = await onToolCall(
                      toolCall.function.name,
                      toolCall.function.arguments
                    );
                    
                    // Add tool result to conversation
                    conversation.push({
                      role: 'tool',
                      content: result
                    });
                    
                    onChunk({
                      type: 'tool_call_end',
                      toolCall,
                      result
                    });
                  } catch (error) {
                    const errorMsg = `Tool execution failed: ${error.message}`;
                    conversation.push({
                      role: 'tool',
                      content: errorMsg
                    });
                    
                    onChunk({
                      type: 'tool_call_error',
                      toolCall,
                      error: errorMsg
                    });
                  }
                }
                
                // Continue the loop to get next response
                break;
              } else {
                // No tool calls, we're done
                if (assistantMessage.content) {
                  conversation.push(assistantMessage);
                }
                
                onChunk({ type: 'done' });
                return conversation;
              }
            }
          } catch (error) {
            console.error('Error parsing streaming response:', error, line);
          }
        }
      }
      
      // If we had tool calls, continue the loop
      if (toolCalls.length > 0) {
        continue;
      } else {
        // No tool calls, we're done
        onChunk({ type: 'done' });
        return conversation;
      }
      
    } catch (error) {
      console.error('Stream error:', error);
      onChunk({
        type: 'error',
        error: error.message
      });
      throw error;
    }
  }
  
  // Max iterations reached
  onChunk({
    type: 'content',
    content: '\n\n[Reached maximum tool-call iterations]'
  });
  onChunk({ type: 'done' });
  
  return conversation;
}
