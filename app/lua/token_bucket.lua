-- KEYS[1] : key prefix, e.g. "rl:token"
-- ARGV[1] : capacity (int)
-- ARGV[2] : refill_rate (tokens per second)
-- ARGV[3] : api_key (identifier)
--
-- Returns { allowed, remaining, reset_at, limit }

local now         = tonumber(redis.call('TIME')[1])
local capacity    = tonumber(ARGV[1])
local rate        = tonumber(ARGV[2])
local identifier  = ARGV[3]

local key = KEYS[1] .. ':' .. identifier

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens      = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens      = capacity
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end

redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)

-- TTL: how long until the bucket would be full again (min 60s), guarded for rate=0
local ttl = 3600
if rate > 0 then
    ttl = math.max(60, math.ceil(capacity / rate) + 1)
end
redis.call('EXPIRE', key, ttl)

local remaining = math.floor(tokens)
local reset_at  = now + math.ceil((capacity - tokens) / math.max(rate, 0.001))

return { allowed, remaining, reset_at, capacity }