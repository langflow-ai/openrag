#!/usr/bin/env node

// Wrapper to patch puppeteer launch to add --no-sandbox for CI environments
const Module = require('module');
const { spawn } = require('child_process');

const originalRequire = Module.prototype.require;

Module.prototype.require = function(id) {
  const module = originalRequire.apply(this, arguments);

  if (id === 'puppeteer' || id === 'puppeteer-core') {
    const originalLaunch = module.launch;
    module.launch = async function(options = {}) {
      const args = options.args || [];
      if (!args.includes('--no-sandbox')) {
        args.push('--no-sandbox', '--disable-setuid-sandbox');
      }
      console.log('Launching puppeteer with args:', args);
      return originalLaunch.call(this, { ...options, args });
    };
  }

  return module;
};

// Run npx docusaurus-to-pdf with our patched require
const child = spawn('npx', ['docusaurus-to-pdf'], {
  stdio: 'inherit',
  shell: true
});

child.on('exit', (code) => {
  process.exit(code);
});
