OPENQASM 3.0;
include "stdgates.inc";
qubit[3] q;
cry(pi/8) q[0], q[1];
ry(pi/8) q[1];
cry(pi/8) q[1], q[2];
