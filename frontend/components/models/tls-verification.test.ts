import { describe, expect, it } from "vitest";
import {
  isDefaultTlsSetting,
  isTlsVerificationDisabled,
  parseTlsSetting,
} from "./tls-verification";

describe("parseTlsSetting", () => {
  it.each([
    undefined,
    null,
    "",
    "  ",
    "true",
    "TRUE",
    "1",
    "yes",
    " on ",
  ])("reads %j as verify against the default trust store", (value) => {
    expect(parseTlsSetting(value)).toEqual({ enabled: true, caPath: "" });
  });

  it.each([
    "false",
    " Off ",
    "0",
    "no",
    "FALSE",
  ])("reads %j as verification disabled", (value) => {
    expect(parseTlsSetting(value)).toEqual({ enabled: false, caPath: "" });
  });

  it.each([
    "/var/run/secrets/ca.crt",
    "bogus",
  ])("reads %j as a CA path, keeping verification on", (value) => {
    // An unrecognised word fails closed, as the backend does: it is a path,
    // never a way to switch verification off.
    expect(parseTlsSetting(value)).toEqual({ enabled: true, caPath: value });
  });
});

describe("isTlsVerificationDisabled", () => {
  it.each([
    ["false", true],
    ["Off", true],
    ["", false],
    ["true", false],
    ["/ca.crt", false],
    [undefined, false],
  ])("is %j → %s", (value, expected) => {
    expect(isTlsVerificationDisabled(value)).toBe(expected);
  });
});

describe("isDefaultTlsSetting", () => {
  it.each([
    ["", true],
    [undefined, true],
    ["yes", true],
    ["false", false],
    ["/ca.crt", false],
  ])("is %j → %s", (value, expected) => {
    expect(isDefaultTlsSetting(value)).toBe(expected);
  });
});
