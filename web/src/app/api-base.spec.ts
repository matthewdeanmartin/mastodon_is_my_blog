import { getApiBaseUrl } from './api-base';

describe('getApiBaseUrl', () => {
  it('uses the current origin when already on port 8000', () => {
    expect(
      getApiBaseUrl({
        protocol: 'http:',
        hostname: '127.0.0.1',
        port: '8000',
        origin: 'http://127.0.0.1:8000',
      }),
    ).toBe('http://127.0.0.1:8000');
  });

  it('keeps the current hostname and switches to port 8000 when needed', () => {
    expect(
      getApiBaseUrl({
        protocol: 'http:',
        hostname: '127.0.0.1',
        port: '4200',
        origin: 'http://127.0.0.1:4200',
      }),
    ).toBe('http://127.0.0.1:8000');
  });
});
