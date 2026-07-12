import { getApiBaseUrl } from './api-base';

describe('getApiBaseUrl', () => {
  it('uses the current origin when already on port 8100', () => {
    expect(
      getApiBaseUrl({
        protocol: 'http:',
        hostname: '127.0.0.1',
        port: '8100',
        origin: 'http://127.0.0.1:8100',
      }),
    ).toBe('http://127.0.0.1:8100');
  });

  it('keeps the current hostname and switches to port 8100 when needed', () => {
    expect(
      getApiBaseUrl({
        protocol: 'http:',
        hostname: '127.0.0.1',
        port: '4200',
        origin: 'http://127.0.0.1:4200',
      }),
    ).toBe('http://127.0.0.1:8100');
  });
});
