import type { Holding, ModuleFeed, StocksData } from '@/modules/types';
import { readPortfolio } from '@/config/portfolio';

/**
 * Live quotes from Yahoo's chart endpoint.
 *
 * One request per symbol, issued in parallel. The chart endpoint is used rather
 * than the quote endpoint because the latter now requires a crumb/cookie pair,
 * and because a single call gives both the current price and the history the
 * 3D graph needs.
 *
 * Positions come from config; prices, changes and history are live. A symbol
 * that fails is dropped rather than poisoning the whole portfolio.
 */

const CHART = 'https://query1.finance.yahoo.com/v8/finance/chart';

interface ChartResponse {
  chart: {
    result?: Array<{
      meta: {
        symbol: string;
        currency: string;
        regularMarketPrice: number;
        chartPreviousClose?: number;
        previousClose?: number;
      };
      timestamp?: number[];
      indicators: { quote: Array<{ close?: Array<number | null> }> };
    }>;
    error?: { description?: string };
  };
}

async function fetchSymbol(
  symbol: string,
  signal: AbortSignal,
): Promise<{ price: number; previousClose: number; currency: string; history: number[] } | null> {
  const url = `${CHART}/${encodeURIComponent(symbol)}?range=1mo&interval=1d`;
  try {
    const response = await fetch(url, {
      signal,
      headers: { 'user-agent': 'Mozilla/5.0 (compatible; NEXUS/1.0)' },
      next: { revalidate: 60 },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as ChartResponse;
    const result = body.chart.result?.[0];
    if (!result) return null;

    const closes = (result.indicators.quote[0]?.close ?? []).filter(
      (v): v is number => typeof v === 'number' && Number.isFinite(v),
    );
    const price = result.meta.regularMarketPrice ?? closes[closes.length - 1] ?? 0;
    const previousClose =
      result.meta.chartPreviousClose ?? result.meta.previousClose ?? closes[closes.length - 2] ?? price;

    return { price, previousClose, currency: result.meta.currency ?? 'USD', history: closes };
  } catch {
    return null;
  }
}

export async function fetchStocks(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<StocksData>> {
  const positions = readPortfolio();
  const quotes = await Promise.all(positions.map((p) => fetchSymbol(p.symbol, signal)));

  const holdings: Holding[] = [];
  for (let i = 0; i < positions.length; i++) {
    const position = positions[i]!;
    const quote = quotes[i];
    if (!quote || quote.price <= 0) continue;

    const value = quote.price * position.units;
    const cost = position.costBasis * position.units;
    holdings.push({
      symbol: position.symbol,
      name: position.name,
      sector: position.sector,
      units: position.units,
      price: quote.price,
      previousClose: quote.previousClose,
      changePct: quote.previousClose ? ((quote.price - quote.previousClose) / quote.previousClose) * 100 : 0,
      currency: quote.currency,
      value,
      costBasis: position.costBasis,
      pnl: value - cost,
      pnlPct: cost ? ((value - cost) / cost) * 100 : 0,
      history: quote.history.slice(-22),
    });
  }

  if (holdings.length === 0) {
    throw new Error('No quotes returned for any position');
  }

  const totalValue = holdings.reduce((sum, h) => sum + h.value, 0);
  const totalCost = holdings.reduce((sum, h) => sum + h.costBasis * h.units, 0);
  const previousValue = holdings.reduce((sum, h) => sum + h.previousClose * h.units, 0);

  const bySector = new Map<string, number>();
  for (const holding of holdings) {
    bySector.set(holding.sector, (bySector.get(holding.sector) ?? 0) + holding.value);
  }

  return {
    status: 'live',
    error: null,
    fetchedAt: Date.now(),
    source: 'Yahoo Finance',
    data: {
      holdings: holdings.sort((a, b) => b.value - a.value),
      totalValue,
      totalCost,
      totalPnl: totalValue - totalCost,
      totalPnlPct: totalCost ? ((totalValue - totalCost) / totalCost) * 100 : 0,
      dayChangePct: previousValue ? ((totalValue - previousValue) / previousValue) * 100 : 0,
      allocation: [...bySector.entries()]
        .map(([label, value]) => ({ label, value, weight: value / totalValue }))
        .sort((a, b) => b.weight - a.weight),
      // US cash equities, roughly. Good enough to label the readout honestly.
      marketOpen: isMarketOpen(),
    },
  };
}

function isMarketOpen(): boolean {
  const now = new Date();
  const utcDay = now.getUTCDay();
  if (utcDay === 0 || utcDay === 6) return false;
  const minutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  // 14:30–21:00 UTC covers New York's session outside DST edge cases.
  return minutes >= 870 && minutes <= 1260;
}
