# Install with pipx

This is the cleanest way to install Mastodon is My Blog (MIMB) as an isolated Python app.

## When to choose this path

Choose `pipx` if you want:

- the MIMB command installed globally
- Python dependencies kept separate from your other projects
- a cleaner command-line setup

## Before you begin

You will still need:

- **Python 3.12 or newer**
- **Node.js and npm** for the web interface
- a **Mastodon account**
- permission to create an app on your Mastodon server

## Install the CLI

If you are installing straight from the repository:

```bash
pipx install git+https://github.com/matthewmartin/mastodon_is_my_blog.git
```

If you already cloned the repository:

```bash
cd C:\path\to\mastodon_is_my_blog
pipx install .
```

## Set up your Mastodon account

Run:

```bash
mastodon_is_my_blog init
```

MIMB will ask for:

1. an account name you will recognize locally
2. your Mastodon server URL
3. the client ID and client secret from the Mastodon app you created
4. optionally, an access token right away

## Start the backend

```bash
mastodon_is_my_blog start --reload
```

## Start the web interface

The Angular web app lives in the repository, so for the full browser experience you should also clone the repo and run:

```bash
cd C:\path\to\mastodon_is_my_blog\web
npm install
npm start
```

Then open `http://localhost:4200`.

## Best for

This path is best if you want the CLI installed in a tidy way but still plan to run the local web interface from a checkout of the repository.
