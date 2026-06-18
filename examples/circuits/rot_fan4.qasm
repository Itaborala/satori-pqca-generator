OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
rx(pi/6) q[0];
crx(pi/6) q[0], q[1];
crx(pi/6) q[0], q[2];
crx(pi/6) q[0], q[3];
