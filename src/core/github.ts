import { execa } from 'execa';
import type { GitHubCliStatus } from '../types/index.js';

export class GitHubCliProvider {
  /** Check CLI availability without reading credentials. */
  async isAvailable(): Promise<boolean> {
    try {
      await execa('gh', ['--version'], { timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  }

  /** Read login metadata; never request tokens or return raw command errors. */
  async getAuthStatus(): Promise<GitHubCliStatus> {
    const isAvailable = await this.isAvailable();
    const unavailable: GitHubCliStatus = {
      isAvailable, isLoggedIn: false, username: null, activeHosts: [], error: null,
    };
    if (!isAvailable) {
      return { ...unavailable, error: 'GitHub CLI not available. Install gh, then run gh auth login.' };
    }
    try {
      const { stdout, stderr } = await execa('gh', ['auth', 'status'], { timeout: 10000 });
      const output = `${stdout}\n${stderr}`;
      const accounts = [...output.matchAll(/Logged in to ([\w.-]+) (?:account|as) ([\w-]+)/g)];
      if (accounts.length === 0) {
        return { ...unavailable, error: 'Could not confirm GitHub login. Run gh auth status or gh auth login.' };
      }
      return {
        isAvailable: true,
        isLoggedIn: true,
        username: accounts[0][2],
        activeHosts: [...new Set(accounts.map(account => account[1]))],
        error: null,
      };
    } catch {
      // CLI errors can contain stdout/stderr with credential material.
      return { ...unavailable, error: 'GitHub authentication check failed or timed out. Run gh auth status, then gh auth login if needed.' };
    }
  }

  /** Return the installed CLI version with a bounded execution time. */
  async getVersion(): Promise<string | null> {
    try {
      const { stdout } = await execa('gh', ['--version'], { timeout: 5000 });
      return stdout.split('\n')[0] || null;
    } catch {
      return null;
    }
  }
}
