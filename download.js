"use strict";

const fsp = require("fs/promises");
const path = require("path");

let getHistoricalRates;
try {
  ({ getHistoricalRates } = require("dukascopy-node"));
} catch (error) {
  console.error(
    "Missing dependency 'dukascopy-node'. Install it with 'npm install' before running download.js."
  );
  process.exit(1);
}

const INSTRUMENTS = require("./config/instruments.json");

const DEFAULTS = {
  symbols: "all",
  lookbackDays: 90,
  batchSize: 4,
  batchPause: 2000,
  retries: 8,
  retryPause: 1000,
  retryOnEmpty: true,
  useCache: true,
  skipExisting: true,
  overwrite: false,
  failFast: false,
  failAfterRetries: true,
  fallbackSliceHours: 1,
  silent: false,
};

const GROUPS = INSTRUMENTS.reduce((acc, item) => {
  const key = item.assetClass.toUpperCase();
  acc[key] = acc[key] || [];
  acc[key].push(item.symbol);
  return acc;
}, {});

const GROUP_ALIASES = {
  ALL: [...INSTRUMENTS.map((item) => item.symbol)],
  FOREX: GROUPS.FOREX || [],
  INDEX: GROUPS.INDEX || [],
  INDICES: GROUPS.INDEX || [],
  COMMODITY: GROUPS.COMMODITY || [],
  COMMODITIES: GROUPS.COMMODITY || [],
  CRYPTO: GROUPS.CRYPTO || [],
};

function printHelp() {
  console.log(`
Usage:
  node download.js --symbols all --from 2026-01-01 --to 2026-03-31

Options:
  --symbols           all | comma-separated symbols/groups (default: all)
  --from              Inclusive start date in YYYY-MM-DD
  --to                Inclusive end date in YYYY-MM-DD
  --lookback-days     Used when --from/--to are omitted (default: 90)
  --raw-dir           Raw output root (default: data/raw)
  --log-dir           Log output root (default: logs/downloads)
  --cache-dir         Dukascopy artifact cache root (default: data/cache/dukascopy)
  --batch-size        Dukascopy batch size (default: 4)
  --batch-pause       Pause between Dukascopy batches in ms (default: 2000)
  --retries           Artifact retry count (default: 8)
  --retry-pause       Pause between retries in ms (default: 1000)
  --retry-on-empty    Retry empty 0-byte artifacts (default: true)
  --no-retry-on-empty Disable retry-on-empty
  --fallback-slice-hours
                      On day-level failure, retry the day in N-hour slices (default: 1)
  --cache             Enable Dukascopy cache (default: true)
  --no-cache          Disable cache
  --overwrite         Replace existing daily files
  --no-skip-existing  Re-download existing files unless --overwrite is false
  --fail-fast         Stop on the first failed day
  --silent            Reduce console output
  --help              Show this message

Supported symbol groups:
  all, forex, index, indices, commodity, commodities, crypto
`);
}

function parseArgs(argv) {
  const args = {
    rawDir: path.join(process.cwd(), "data", "raw"),
    logDir: path.join(process.cwd(), "logs", "downloads"),
    cacheDir: path.join(process.cwd(), "data", "cache", "dukascopy"),
    ...DEFAULTS,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      continue;
    }

    const key = token.slice(2);
    switch (key) {
      case "symbols":
        args.symbols = argv[++i];
        break;
      case "from":
        args.from = argv[++i];
        break;
      case "to":
        args.to = argv[++i];
        break;
      case "lookback-days":
        args.lookbackDays = Number(argv[++i]);
        break;
      case "raw-dir":
        args.rawDir = path.resolve(argv[++i]);
        break;
      case "log-dir":
        args.logDir = path.resolve(argv[++i]);
        break;
      case "cache-dir":
        args.cacheDir = path.resolve(argv[++i]);
        break;
      case "batch-size":
        args.batchSize = Number(argv[++i]);
        break;
      case "batch-pause":
        args.batchPause = Number(argv[++i]);
        break;
      case "retries":
        args.retries = Number(argv[++i]);
        break;
      case "retry-pause":
        args.retryPause = Number(argv[++i]);
        break;
      case "retry-on-empty":
        args.retryOnEmpty = true;
        break;
      case "no-retry-on-empty":
        args.retryOnEmpty = false;
        break;
      case "fallback-slice-hours":
        args.fallbackSliceHours = Number(argv[++i]);
        break;
      case "cache":
        args.useCache = true;
        break;
      case "no-cache":
        args.useCache = false;
        break;
      case "overwrite":
        args.overwrite = true;
        args.skipExisting = false;
        break;
      case "no-skip-existing":
        args.skipExisting = false;
        break;
      case "fail-fast":
        args.failFast = true;
        break;
      case "no-fail-after-retries":
        args.failAfterRetries = false;
        break;
      case "silent":
        args.silent = true;
        break;
      case "help":
        args.help = true;
        break;
      default:
        throw new Error(`Unknown argument: ${token}`);
    }
  }

  return args;
}

function parseUtcDate(dateText, label) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateText || ""));
  if (!match) {
    throw new Error(`${label} must use YYYY-MM-DD format.`);
  }

  const [, yearText, monthText, dayText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    Number.isNaN(date.getTime()) ||
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    throw new Error(`${label} is not a valid calendar date: ${dateText}`);
  }
  return date;
}

function addDays(date, amount) {
  const copy = new Date(date.getTime());
  copy.setUTCDate(copy.getUTCDate() + amount);
  return copy;
}

function addHours(date, amount) {
  const copy = new Date(date.getTime());
  copy.setUTCHours(copy.getUTCHours() + amount);
  return copy;
}

function formatDay(date) {
  return date.toISOString().slice(0, 10);
}

function computeDateWindow(options) {
  if (options.from && options.to) {
    const from = parseUtcDate(options.from, "--from");
    const to = parseUtcDate(options.to, "--to");
    if (from > to) {
      throw new Error("--from cannot be later than --to.");
    }
    return { from, to };
  }

  if (options.from || options.to) {
    throw new Error("Provide both --from and --to together, or omit both and use --lookback-days.");
  }

  const now = new Date();
  const todayUtc = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const to = addDays(todayUtc, -1);
  const lookbackDays = Number.isFinite(options.lookbackDays) ? Math.max(1, options.lookbackDays) : 90;
  const from = addDays(to, -(lookbackDays - 1));
  return { from, to };
}

function resolveSymbols(symbolSpec) {
  if (!symbolSpec || symbolSpec.toLowerCase() === "all") {
    return [...INSTRUMENTS];
  }

  const resolved = new Map();
  const tokens = symbolSpec
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);

  for (const token of tokens) {
    const upper = token.toUpperCase();
    if (GROUP_ALIASES[upper]) {
      for (const symbol of GROUP_ALIASES[upper]) {
        const item = INSTRUMENTS.find((entry) => entry.symbol === symbol);
        resolved.set(item.symbol, item);
      }
      continue;
    }

    const item = INSTRUMENTS.find(
      (entry) => entry.symbol === upper || entry.instrumentId.toUpperCase() === upper
    );
    if (!item) {
      throw new Error(`Unknown symbol or group: ${token}`);
    }
    resolved.set(item.symbol, item);
  }

  return [...resolved.values()];
}

class Logger {
  constructor(filePath, silent = false) {
    this.filePath = filePath;
    this.silent = silent;
  }

  async init() {
    await fsp.mkdir(path.dirname(this.filePath), { recursive: true });
  }

  async write(level, message) {
    const line = `${new Date().toISOString()} [${level}] ${message}\n`;
    await fsp.appendFile(this.filePath, line, "utf8");
    if (!this.silent) {
      const output = level === "ERROR" ? console.error : level === "WARN" ? console.warn : console.log;
      output(line.trimEnd());
    }
  }

  info(message) {
    return this.write("INFO", message);
  }

  warn(message) {
    return this.write("WARN", message);
  }

  error(message) {
    return this.write("ERROR", message);
  }
}

async function fileExists(filePath) {
  try {
    const stats = await fsp.stat(filePath);
    return stats.isFile() && stats.size > 0;
  } catch (error) {
    return false;
  }
}

function csvHasData(csvText) {
  if (!csvText) {
    return false;
  }
  const trimmed = String(csvText).trim();
  if (!trimmed) {
    return false;
  }
  const firstNewLine = trimmed.indexOf("\n");
  if (firstNewLine === -1) {
    return false;
  }
  return trimmed.slice(firstNewLine + 1).trim().length > 0;
}

function countCsvRows(csvText) {
  if (!csvHasData(csvText)) {
    return 0;
  }
  const trimmed = String(csvText).trim();
  let lineBreaks = 0;
  for (const character of trimmed) {
    if (character === "\n") {
      lineBreaks += 1;
    }
  }
  return Math.max(0, lineBreaks);
}

async function writeAtomic(filePath, content) {
  await fsp.mkdir(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.tmp`;
  await fsp.writeFile(tempPath, content, "utf8");
  await fsp.rm(filePath, { force: true });
  await fsp.rename(tempPath, filePath);
}

async function downloadDay(instrument, dayStart, options, logger) {
  const nextDay = addDays(dayStart, 1);
  const outDir = path.join(options.rawDir, instrument.symbol);
  const filePath = path.join(outDir, `${formatDay(dayStart)}.csv`);

  if (!options.overwrite && options.skipExisting && (await fileExists(filePath))) {
    await logger.info(`Skipping ${instrument.symbol} ${formatDay(dayStart)} because the file already exists.`);
    return { status: "skipped", filePath, rows: 0 };
  }

  await logger.info(
    `Downloading ${instrument.symbol} (${instrument.instrumentId}) for ${formatDay(dayStart)} -> ${formatDay(nextDay)}`
  );

  let csv;
  try {
    csv = await getHistoricalRates({
      instrument: instrument.instrumentId,
      dates: {
        from: dayStart,
        to: nextDay,
      },
      timeframe: "tick",
      format: "csv",
      batchSize: options.batchSize,
      pauseBetweenBatchesMs: options.batchPause,
      useCache: options.useCache,
      cacheFolderPath: options.cacheDir,
      retryCount: options.retries,
      retryOnEmpty: options.retryOnEmpty,
      failAfterRetryCount: options.failAfterRetries,
      pauseBetweenRetriesMs: options.retryPause,
    });
  } catch (error) {
    if (options.fallbackSliceHours > 0 && options.fallbackSliceHours < 24) {
      await logger.warn(
        `Day request failed for ${instrument.symbol} ${formatDay(dayStart)} (${error.message}). Retrying in ${options.fallbackSliceHours}-hour slices.`
      );
      csv = await downloadDayInSlices(instrument, dayStart, options, logger);
    } else {
      throw error;
    }
  }

  if (!csvHasData(csv)) {
    await logger.warn(`No tick rows returned for ${instrument.symbol} on ${formatDay(dayStart)}.`);
    return { status: "empty", filePath, rows: 0 };
  }

  await writeAtomic(filePath, csv.endsWith("\n") ? csv : `${csv}\n`);
  const rows = countCsvRows(csv);
  await logger.info(`Saved ${instrument.symbol} ${formatDay(dayStart)} to ${filePath} (${rows} rows).`);
  return { status: "downloaded", filePath, rows };
}

async function downloadDayInSlices(instrument, dayStart, options, logger) {
  const headers = [];
  const bodyLines = [];
  const dayEnd = addDays(dayStart, 1);
  let sliceStart = new Date(dayStart.getTime());

  while (sliceStart < dayEnd) {
    const sliceEnd = new Date(
      Math.min(addHours(sliceStart, options.fallbackSliceHours).getTime(), dayEnd.getTime())
    );
    await logger.info(
      `Downloading slice ${instrument.symbol} ${sliceStart.toISOString()} -> ${sliceEnd.toISOString()}`
    );
    const csv = await getHistoricalRates({
      instrument: instrument.instrumentId,
      dates: {
        from: sliceStart,
        to: sliceEnd,
      },
      timeframe: "tick",
      format: "csv",
      batchSize: Math.max(1, Math.min(options.batchSize, options.fallbackSliceHours)),
      pauseBetweenBatchesMs: options.batchPause,
      useCache: options.useCache,
      cacheFolderPath: options.cacheDir,
      retryCount: options.retries,
      retryOnEmpty: options.retryOnEmpty,
      failAfterRetryCount: options.failAfterRetries,
      pauseBetweenRetriesMs: options.retryPause,
    });

    if (csvHasData(csv)) {
      const lines = String(csv).trim().split(/\r?\n/);
      if (lines.length > 0) {
        if (headers.length === 0) {
          headers.push(lines[0]);
        }
        bodyLines.push(...lines.slice(1));
      }
    }

    sliceStart = sliceEnd;
  }

  if (headers.length === 0 || bodyLines.length === 0) {
    return "";
  }

  return `${headers[0]}\n${bodyLines.join("\n")}\n`;
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error.message);
    printHelp();
    process.exit(1);
  }

  if (options.help) {
    printHelp();
    return;
  }

  const { from, to } = computeDateWindow(options);
  const symbols = resolveSymbols(options.symbols);

  const runStamp = new Date().toISOString().replace(/[:.]/g, "-");
  const logPath = path.join(options.logDir, `download-${runStamp}.log`);
  const logger = new Logger(logPath, options.silent);
  await logger.init();

  await fsp.mkdir(options.rawDir, { recursive: true });
  await fsp.mkdir(options.cacheDir, { recursive: true });

  const summary = {
    startedAt: new Date().toISOString(),
    symbols: symbols.map((item) => item.symbol),
    dateRange: {
      from: formatDay(from),
      to: formatDay(to),
    },
    options: {
      batchSize: options.batchSize,
      batchPause: options.batchPause,
      retries: options.retries,
      retryPause: options.retryPause,
      retryOnEmpty: options.retryOnEmpty,
      useCache: options.useCache,
      overwrite: options.overwrite,
      skipExisting: options.skipExisting,
      failFast: options.failFast,
    },
    stats: {
      downloaded: 0,
      skipped: 0,
      empty: 0,
      failed: 0,
      rows: 0,
    },
    failures: [],
  };

  await logger.info(
    `Starting download run for ${symbols.length} symbols from ${formatDay(from)} to ${formatDay(to)}.`
  );

  for (const instrument of symbols) {
    for (let cursor = new Date(from.getTime()); cursor <= to; cursor = addDays(cursor, 1)) {
      try {
        const result = await downloadDay(instrument, cursor, options, logger);
        summary.stats[result.status] += 1;
        summary.stats.rows += result.rows || 0;
      } catch (error) {
        summary.stats.failed += 1;
        summary.failures.push({
          symbol: instrument.symbol,
          instrumentId: instrument.instrumentId,
          date: formatDay(cursor),
          error: error.message,
        });
        await logger.error(
          `Failed ${instrument.symbol} ${formatDay(cursor)}: ${error.stack || error.message}`
        );
        if (options.failFast) {
          throw error;
        }
      }
    }
  }

  summary.finishedAt = new Date().toISOString();
  const summaryPath = path.join(options.logDir, `download-${runStamp}.summary.json`);
  await fsp.writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  await logger.info(`Download run completed. Summary written to ${summaryPath}.`);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
