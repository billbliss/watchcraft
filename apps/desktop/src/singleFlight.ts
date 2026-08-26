export function singleFlight<Arguments extends unknown[], Result>(
  operation: (...args: Arguments) => Promise<Result>,
): (...args: Arguments) => Promise<Result> {
  let inFlight: Promise<Result> | null = null;

  return (...args: Arguments): Promise<Result> => {
    if (inFlight) return inFlight;

    const request = operation(...args);
    inFlight = request;
    const clear = (): void => {
      if (inFlight === request) inFlight = null;
    };
    void request.then(clear, clear);
    return request;
  };
}
