from enum import Enum


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class TopicAction(str, Enum):
    like = "like"
    maybe = "maybe"
    skip = "skip"
    used = "used"
    blacklist = "blacklist"
