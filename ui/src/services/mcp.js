/**
 * MCP Bridge service - Connect to bridge server and call tools
 */

import axios from 'axios';
import { BRIDGE_URL } from '../config.js';

const api = axios.create({
  baseURL: BRIDGE_URL,
  timeout: 120000 // 2 minutes for long-running tools
});

/**
 * Check bridge health
 */
export async function checkHealth() {
  try {
    const response = await api.get('/health');
    return response.data;
  } catch (error) {
    console.error('Bridge health check failed:', error);
    throw new Error('Bridge server not accessible');
  }
}

/**
 * Get available tools
 */
export async function getTools() {
  try {
    const response = await api.get('/tools');
    return response.data.tools || [];
  } catch (error) {
    console.error('Failed to get tools:', error);
    throw error;
  }
}

/**
 * Call a tool
 */
export async function callTool(name, args = {}) {
  try {
    const response = await api.post('/tools/call', {
      name,
      arguments: args
    });
    
    return response.data.result;
  } catch (error) {
    console.error(`Failed to call tool ${name}:`, error);
    throw error;
  }
}

/**
 * Get downloaded files
 */
export async function getFiles() {
  try {
    const response = await api.get('/files');
    return response.data.files || [];
  } catch (error) {
    console.error('Failed to get files:', error);
    return [];
  }
}

/**
 * Get file download URL
 */
export function getFileUrl(filename) {
  return `${BRIDGE_URL}/files/${filename}`;
}
