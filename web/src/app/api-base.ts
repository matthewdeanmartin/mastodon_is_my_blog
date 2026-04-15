interface LocationLike {
  protocol: string;
  hostname: string;
  port: string;
  origin: string;
}

export function getApiBaseUrl(currentLocation?: LocationLike): string {
  if (!currentLocation && typeof window === 'undefined') {
    return 'http://localhost:8000';
  }

  const location = currentLocation ?? window.location;
  const { protocol, hostname, port, origin } = location;
  if (port === '8000') {
    return origin;
  }

  return `${protocol}//${hostname}:8000`;
}
