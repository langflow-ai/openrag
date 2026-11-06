const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const childProcess = require('node:child_process');
const {test} = require('node:test');

// Exercise the installed integration and real open 11 module without launching a browser.
test('Docusaurus opens URLs with open 11 from CommonJS', {skip: process.platform !== 'linux'}, async () => {
  const originalSpawn = childProcess.spawn;
  const launches = [];
  let fail = false;
  childProcess.spawn = (command, args, options) => {
    launches.push({command, args, options});
    const child = new EventEmitter();
    child.unref = () => {};
    process.nextTick(() => child.emit(fail ? 'error' : 'spawn', new Error('launch failed')));
    return child;
  };
  const integration = require.resolve('@docusaurus/core/lib/commands/utils/openBrowser/openBrowser.js');
  const originalBrowser = process.env.DOCUSAURUS_BROWSER;
  const originalArgs = process.env.DOCUSAURUS_BROWSER_ARGS;
  try {
    // Default browser, a named shortcut (apps is a named export), and a custom executable.
    for (const browser of ['', 'firefox', 'custom-browser']) {
      process.env.DOCUSAURUS_BROWSER = browser;
      process.env.DOCUSAURUS_BROWSER_ARGS = '--private --new-window';
      delete require.cache[integration];
      const openBrowser = require(integration).default;
      const url = 'https://example.com/docs?test=open';
      assert.equal(await openBrowser(url), true);
      const launch = launches.at(-1);
      assert.ok(launch.args.includes(url));
      if (browser) {
        assert.equal(launch.command, browser);
        assert.deepEqual(launch.args.slice(0, 2), ['--private', '--new-window']);
      }
    }
    fail = true;
    assert.equal(await require(integration).default('https://example.com'), false);
  } finally {
    childProcess.spawn = originalSpawn;
    if (originalBrowser === undefined) delete process.env.DOCUSAURUS_BROWSER;
    else process.env.DOCUSAURUS_BROWSER = originalBrowser;
    if (originalArgs === undefined) delete process.env.DOCUSAURUS_BROWSER_ARGS;
    else process.env.DOCUSAURUS_BROWSER_ARGS = originalArgs;
    delete require.cache[integration];
  }
});
