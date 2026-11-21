class PacketDecodeError(Exception):
    """Rejected wire input; caller may drop this datagram and keep receiving.

    Programming errors (TypeError, KeyError, unrelated ValueError) are deliberately
    not part of this contract and must remain visible to callers.
    """

    def __init__(self, message: str, *, reason: str = "malformed_body") -> None:
        super().__init__(message)
        self.reason = reason

