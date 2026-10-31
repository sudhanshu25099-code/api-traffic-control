-- KEYS[1] : key prefix, e.g. "rl:fixed"
-- ARGV[1] : capacity (int)
-- ARGV[2] : window_seconds (int)
-- ARGV[3] : api_key (identifier)
--
-- Returns { allowed, remaining, reset_at, limit }

local now         = tonumber(redis.call('TIME')[1])
local capacity    = tonumber(ARGV[1])
local window_s    = tonumber(ARGV[2])
local identifier  = ARGV[3]

local window_id   = math.floor(now / window_s)
local key         = KEYS[1] .. ':' .. identifier .. ':' .. window_id

local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, window_s + 1)
end

local allowed = 0
if count <= capacity then
    allowed = 1
end

local remaining = math.max(0, capacity - count)
local reset_at  = math.floor((window_id + 1) * window_s)

return { allowed, remaining, reset_at, capacity }