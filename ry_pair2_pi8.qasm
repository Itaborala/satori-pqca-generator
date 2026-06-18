OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
ry(pi/8) q[0];
cry(pi/8) q[0], q[1];
