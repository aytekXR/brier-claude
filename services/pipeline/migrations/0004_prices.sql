-- FR-301: daily UTC closes for the top 100 crypto assets from a published
-- composite source. Close basis only — wicks are never stored, which keeps
-- resolution wick-gaming-proof (METHODOLOGY.md §2).
create table price_daily (
    asset      text not null,
    day        date not null,
    close_usd  numeric not null,
    source     text not null,                    -- e.g. coingecko-composite
    data_gap   boolean not null default false,   -- EC-8: outage/stale data noted; resolution deferred, never improvised
    primary key (asset, day)
);
