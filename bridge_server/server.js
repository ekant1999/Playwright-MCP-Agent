/**
 * Express HTTP bridge for Playwright MCP server
 * Spawns Python MCP server and exposes tools via REST API
 */

import express from 'express';
import cors from 'cors';
import { spawn } from 'child_process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3001;

// Middleware
app.use(cors({
  origin: 'http://localhost:5173',
  credentials: true
}));
app.use(express.json({ limit: '50mb' }));

// State
let mcpClient = null;
let mcpProcess = null;
let availableTools = [];
let isConnected = false;

/**
 * Initialize MCP connection
 */
async function initializeMCP() {
  try {
    console.log('Starting Python MCP server...');
    
    // Use venv Python if available (project root is parent of bridge_server)
    const projectRoot = path.join(__dirname, '..');
    const venvPython = path.join(projectRoot, 'venv', 'bin', 'python3');
    const fs = await import('fs/promises');
    const pythonPath = process.env.PYTHON_PATH || (await fs.access(venvPython).then(() => venvPython).catch(() => 'python3'));
    
    console.log('Using Python:', pythonPath);
    
    // StdioClientTransport spawns the MCP server process when we connect
    const playwrightBrowsersPath = path.join(projectRoot, '.playwright-browsers');
    const transport = new StdioClientTransport({
      command: pythonPath,
      args: ['-m', 'mcp_server.server'],
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: projectRoot,
        PYTHONUNBUFFERED: '1',
        PLAYWRIGHT_BROWSERS_PATH: playwrightBrowsersPath
      }
    });
    
    mcpClient = new Client({
      name: 'playwright-bridge',
      version: '1.0.0'
    }, {
      capabilities: {}
    });
    
    await mcpClient.connect(transport);
    
    console.log('Connected to MCP server');
    isConnected = true;
    
    // List available tools
    const toolsResponse = await mcpClient.listTools();
    availableTools = toolsResponse.tools || [];
    
    console.log(`Loaded ${availableTools.length} tools:`, availableTools.map(t => t.name).join(', '));
    
  } catch (error) {
    console.error('Failed to initialize MCP:', error);
    isConnected = false;
    throw error;
  }
}

/**
 * Health check endpoint
 */
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    mcp_connected: isConnected,
    tools_count: availableTools.length,
    timestamp: new Date().toISOString()
  });
});

/**
 * List available tools
 */
app.get('/tools', async (req, res) => {
  try {
    if (!isConnected) {
      return res.status(503).json({
        error: 'MCP server not connected',
        tools: []
      });
    }
    
    // Refresh tools list
    const toolsResponse = await mcpClient.listTools();
    availableTools = toolsResponse.tools || [];
    
    res.json({
      tools: availableTools.map(tool => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema
      }))
    });
  } catch (error) {
    console.error('Error listing tools:', error);
    res.status(500).json({
      error: error.message,
      tools: []
    });
  }
});

/**
 * Call a tool
 */
app.post('/tools/call', async (req, res) => {
  try {
    const { name, arguments: args } = req.body;
    
    if (!name) {
      return res.status(400).json({
        error: 'Tool name is required'
      });
    }
    
    if (!isConnected) {
      return res.status(503).json({
        error: 'MCP server not connected'
      });
    }
    
    console.log(`Calling tool: ${name}`);
    
    // Call the tool via MCP
    const result = await mcpClient.callTool({
      name,
      arguments: args || {}
    });
    
    // Extract text content from result
    let content = '';
    if (result.content && Array.isArray(result.content)) {
      for (const item of result.content) {
        if (item.type === 'text') {
          content += item.text;
        }
      }
    }
    
    res.json({
      success: true,
      result: content,
      isError: result.isError || false
    });
    
  } catch (error) {
    console.error('Error calling tool:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * List downloaded files
 */
app.get('/files', async (req, res) => {
  try {
    const fs = await import('fs/promises');
    const downloadsPath = path.join(__dirname, '..', 'mcp_server', 'downloads');
    
    // Create directory if it doesn't exist
    try {
      await fs.mkdir(downloadsPath, { recursive: true });
    } catch (e) {}
    
    const files = await fs.readdir(downloadsPath);
    
    const fileStats = await Promise.all(
      files.map(async (filename) => {
        const filePath = path.join(downloadsPath, filename);
        const stats = await fs.stat(filePath);
        return {
          filename,
          size: stats.size,
          modified: stats.mtime.toISOString(),
          path: filePath
        };
      })
    );
    
    res.json({
      files: fileStats.sort((a, b) => new Date(b.modified) - new Date(a.modified))
    });
  } catch (error) {
    console.error('Error listing files:', error);
    res.status(500).json({
      error: error.message,
      files: []
    });
  }
});

/**
 * Download a file
 */
app.get('/files/:filename', async (req, res) => {
  try {
    const { filename } = req.params;
    const downloadsPath = path.join(__dirname, '..', 'mcp_server', 'downloads');
    const filePath = path.join(downloadsPath, filename);
    
    res.download(filePath);
  } catch (error) {
    console.error('Error downloading file:', error);
    res.status(404).json({
      error: 'File not found'
    });
  }
});

/**
 * Start server
 */
async function startServer() {
  try {
    // Initialize MCP connection
    await initializeMCP();
    
    // Start Express server
    app.listen(PORT, () => {
      console.log(`\n✓ Bridge server running on http://localhost:${PORT}`);
      console.log(`✓ MCP connected with ${availableTools.length} tools`);
      console.log(`\nEndpoints:`);
      console.log(`  GET  /health       - Health check`);
      console.log(`  GET  /tools        - List available tools`);
      console.log(`  POST /tools/call   - Call a tool`);
      console.log(`  GET  /files        - List downloaded files`);
      console.log(`  GET  /files/:name  - Download a file\n`);
    });
    
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

// Handle shutdown
process.on('SIGINT', () => {
  console.log('\nShutting down...');
  if (mcpProcess) {
    mcpProcess.kill();
  }
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\nShutting down...');
  if (mcpProcess) {
    mcpProcess.kill();
  }
  process.exit(0);
});

// Start the server
startServer();
